"""Publica o app no GitHub para o celular funcionar sem o computador ligado.

Faz, com o token do .env:
  1. confere repositório, senha e permissões;
  2. cadastra os segredos (NUVEM_SENHA, PLUGGY_CLIENT_ID, PLUGGY_CLIENT_SECRET) — criptografados pelo GitHub;
  3. liga o GitHub Pages;
  4. envia o código (com travas para NUNCA enviar .env, data/ ou senhas);
  5. envia os seus ajustes criptografados, o que dispara o robô pela primeira vez.

Pode rodar de novo sempre que atualizar o app.
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
# Pastas e arquivos que nunca podem ir para o GitHub (o .env.example, sem valores, pode).
FORBIDDEN_DIRS = ("data/", "estado/", "site/")
FORBIDDEN_FILES = (".env", "secret.key")


def fail(msg):
    print(f"\n❌ {msg}")
    sys.exit(1)


def load_env():
    env = {}
    path = ROOT / ".env"
    if not path.exists():
        fail("Arquivo .env não encontrado. Rode o iniciar.bat uma vez ou copie o .env.example para .env.")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def gh(token, method, path, body=None, ok=(200, 201, 204)):
    req = urllib.request.Request(
        "https://api.github.com" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "controle-de-gastos"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            data = json.loads(raw)
        except ValueError:
            data = {"message": raw.decode(errors="replace")[:200]}
        return e.code, data


def git(*args, check=True, extra=()):
    r = subprocess.run(["git", *extra, *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        fail(f"git {args[0]} falhou: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def main():
    env = load_env()
    token, repo, senha = env.get("GITHUB_TOKEN", ""), env.get("GITHUB_REPO", "").strip("/"), env.get("NUVEM_SENHA", "")
    pid, psecret = env.get("PLUGGY_CLIENT_ID", ""), env.get("PLUGGY_CLIENT_SECRET", "")
    if not token or "/" not in repo:
        fail("Preencha GITHUB_TOKEN e GITHUB_REPO (formato: seu-usuario/nome-do-repositorio) no .env.")
    sys.path.insert(0, str(ROOT))
    from financas import nuvem
    try:
        nuvem.check_password(senha)
    except nuvem.NuvemError as e:
        fail(str(e) + " Ajuste NUVEM_SENHA no .env.")
    if not pid or not psecret:
        fail("PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET precisam estar no .env.")

    # 1. repositório
    print(f"1/5 Conferindo o repositório {repo}…")
    status, info = gh(token, "GET", f"/repos/{repo}")
    if status == 404:
        fail(f"Repositório {repo} não encontrado. Crie-o em https://github.com/new (público, vazio) "
             "e confira se o token tem acesso a ele.")
    if status != 200:
        fail(f"GitHub respondeu {status}: {info.get('message')}. Confira o GITHUB_TOKEN.")
    if info.get("private"):
        fail("O repositório é privado: o GitHub Pages grátis só funciona em repositório público. "
             "Seus dados continuam protegidos, pois tudo é enviado criptografado.")

    # 2. segredos
    print("2/5 Cadastrando os segredos no GitHub…")
    from nacl import encoding, public
    status, key = gh(token, "GET", f"/repos/{repo}/actions/secrets/public-key")
    if status != 200:
        fail("O token não pode cadastrar segredos. Dê a permissão 'Secrets: Read and write' ao token.")
    box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
    for name, value in (("NUVEM_SENHA", senha), ("PLUGGY_CLIENT_ID", pid), ("PLUGGY_CLIENT_SECRET", psecret)):
        sealed = base64.b64encode(box.encrypt(value.encode())).decode()
        st, resp = gh(token, "PUT", f"/repos/{repo}/actions/secrets/{name}",
                      {"encrypted_value": sealed, "key_id": key["key_id"]})
        if st not in (201, 204):
            fail(f"Não consegui salvar o segredo {name}: {resp.get('message')}")

    # 3. GitHub Pages
    print("3/5 Ligando o GitHub Pages…")
    st, resp = gh(token, "POST", f"/repos/{repo}/pages", {"build_type": "workflow"})
    if st == 409:  # já existe: garante que publica pelo Actions
        st, resp = gh(token, "PUT", f"/repos/{repo}/pages", {"build_type": "workflow"})
    if st not in (200, 201, 204):
        print(f"   ⚠️ Não consegui ligar o Pages automaticamente ({resp.get('message')}). Ligue à mão: "
              f"https://github.com/{repo}/settings/pages → Source: GitHub Actions.")

    # 4. código
    print("4/5 Enviando o código…")
    if not (ROOT / ".git").exists():
        git("init", "-q", "-b", "main")
    if not git("config", "user.email", check=False):
        git("config", "user.name", "Controle de Gastos")
        git("config", "user.email", "controle-de-gastos@users.noreply.github.com")
    git("add", "-A")
    tracked = git("ls-files", "--cached").splitlines()
    bad = [f for f in tracked if f.startswith(FORBIDDEN_DIRS) or f.rsplit("/", 1)[-1] in FORBIDDEN_FILES
           or f.endswith((".db", ".pdf", ".log"))]
    if bad:
        git("reset", "-q", check=False)
        fail(f"Trava de segurança: arquivos que não podem ir para o GitHub: {bad}")
    staged = git("grep", "--cached", "-I", "-l", "-F", "-e", psecret, "-e", token, "-e", senha, check=False)
    if staged:
        git("reset", "-q", check=False)
        fail(f"Trava de segurança: uma senha/token aparece nestes arquivos: {staged.splitlines()}")
    if git("status", "--porcelain"):
        git("commit", "-q", "-m", "Publicar Controle de Gastos")
    git("remote", "remove", "origin", check=False)
    git("remote", "add", "origin", f"https://github.com/{repo}.git")
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    extra = ("-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {auth}")
    # Traz o que já está no GitHub (ex.: ajustes enviados pelo app, README criado no site) sem apagar nada.
    if subprocess.run(["git", *extra, "fetch", "-q", "origin", "main"], cwd=ROOT, capture_output=True).returncode == 0:
        git("merge", "-q", "--no-edit", "--allow-unrelated-histories", "-X", "ours", "origin/main")
    r = subprocess.run(["git", *extra, "push", "-q", "origin", "main"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        msg = r.stderr.replace(token, "***")[:300]
        hint = " Dê ao token as permissões 'Contents' e 'Workflows' (Read and write)." if "403" in msg or "workflow" in msg else ""
        fail(f"git push falhou: {msg}{hint}")

    # 5. ajustes (dispara o robô)
    print("5/5 Enviando seus ajustes criptografados (isso dispara o robô)…")
    os.environ.update({"GITHUB_TOKEN": token, "GITHUB_REPO": repo, "NUVEM_SENHA": senha})
    from financas.store import Store
    store = Store(ROOT / "data" / "financas.db")
    payload = json.dumps(nuvem.export_ajustes(store), ensure_ascii=False).encode()
    try:
        nuvem.github_put_file(token, repo, "nuvem/ajustes.enc", nuvem.encrypt(payload, senha), "ajustes do computador")
    except nuvem.NuvemError as e:
        fail(str(e))
    git("pull", "-q", "--ff-only", "origin", "main", check=False, extra=extra)

    print(f"""
✅ Pronto!
   Robô:   https://github.com/{repo}/actions  (a primeira rodada leva ~2 min)
   Painel: {nuvem.site_url(repo)}
No celular, abra o painel, digite a senha da nuvem (NUVEM_SENHA) e use "Adicionar à tela inicial".
""")


if __name__ == "__main__":
    main()

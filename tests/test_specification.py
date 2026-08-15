import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class ProjectContractTests(unittest.TestCase):
    def test_root_readme_relative_links_resolve(self) -> None:
        document = PROJECT_ROOT / "README.md"
        broken_links: list[str] = []

        for raw_target in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            target = raw_target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (document.parent / target).resolve().exists():
                broken_links.append(raw_target)

        self.assertEqual(broken_links, [])

    def test_e2ee_runtime_uses_pinned_openmls_suite(self) -> None:
        manifest = (PROJECT_ROOT / "frontend/src-wasm/Cargo.toml").read_text(encoding="utf-8")
        runtime = (PROJECT_ROOT / "frontend/src-wasm/src/lib.rs").read_text(encoding="utf-8")

        self.assertIn('openmls = { version = "=0.9.0-rc.2"', manifest)
        self.assertIn("MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519", runtime)

    def test_frontend_nginx_keeps_runtime_writes_on_tmpfs(self) -> None:
        dockerfile = (PROJECT_ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
        nginx = (PROJECT_ROOT / "frontend/nginx-main.conf").read_text(encoding="utf-8")
        compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

        self.assertIn("COPY nginx-main.conf /etc/nginx/nginx.conf", dockerfile)
        for directive in (
            "pid /tmp/nginx.pid;",
            "client_body_temp_path /tmp/client_temp;",
            "proxy_temp_path /tmp/proxy_temp;",
            "fastcgi_temp_path /tmp/fastcgi_temp;",
            "uwsgi_temp_path /tmp/uwsgi_temp;",
            "scgi_temp_path /tmp/scgi_temp;",
        ):
            self.assertIn(directive, nginx)
        self.assertIn("tmpfs: [/tmp]", compose)


if __name__ == "__main__":
    unittest.main()

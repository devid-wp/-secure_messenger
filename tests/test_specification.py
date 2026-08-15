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


if __name__ == "__main__":
    unittest.main()

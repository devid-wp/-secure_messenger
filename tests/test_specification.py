import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = PROJECT_ROOT / "docs"
REQUIRED_DOCUMENTS = {
    "README.md",
    "product-v1.md",
    "domain-model.md",
    "message-lifecycle.md",
    "security-model.md",
    "recovery.md",
    "e2ee-protocol.md",
}
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class SpecificationSmokeTests(unittest.TestCase):
    def test_required_stage_one_documents_exist(self) -> None:
        actual_documents = {
            path.name for path in DOCS_ROOT.glob("*.md") if path.is_file()
        }
        self.assertTrue(REQUIRED_DOCUMENTS.issubset(actual_documents))

    def test_relative_markdown_links_resolve(self) -> None:
        markdown_files = [PROJECT_ROOT / "README.md", *DOCS_ROOT.glob("*.md")]
        broken_links: list[str] = []

        for document in markdown_files:
            content = document.read_text(encoding="utf-8")
            for raw_target in MARKDOWN_LINK.findall(content):
                target = raw_target.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved_target = (document.parent / target).resolve()
                if not resolved_target.exists():
                    broken_links.append(f"{document.name}: {raw_target}")

        self.assertEqual(broken_links, [])

    def test_e2ee_decision_is_explicit(self) -> None:
        decision = (DOCS_ROOT / "e2ee-protocol.md").read_text(encoding="utf-8")
        self.assertIn("RFC 9420", decision)
        self.assertIn("OpenMLS 0.8.1", decision)
        self.assertIn("MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519", decision)
        self.assertIn("WASM", decision)
        self.assertIn("security gate", decision)


if __name__ == "__main__":
    unittest.main()

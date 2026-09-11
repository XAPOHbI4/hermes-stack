import importlib.util, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "build_sources.py"
spec = importlib.util.spec_from_file_location("build_sources", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class BuildSourcesTest(unittest.TestCase):
    def test_manifest_counts_unique_transcripts_and_preserves_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); source = base / "course"; root = base / "module"
            (source / "Урок 1").mkdir(parents=True); (source / "Урок 2").mkdir()
            (source / "Урок 1" / "Субтитры.txt").write_text("один", encoding="utf-8")
            (source / "Урок 2" / "Субтитры.txt").write_text("один", encoding="utf-8")
            (source / "Урок 2" / "Задание.txt").write_text("два", encoding="utf-8")
            result = module.build(source, root)
            self.assertEqual((result["source_file_count"], result["subtitle_count"], result["unique_subtitle_count"]), (3, 2, 1))
            self.assertTrue((root / "references" / "source" / "Урок 2" / "Задание.txt").is_file())

if __name__ == "__main__": unittest.main()

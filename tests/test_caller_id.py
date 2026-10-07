import importlib.util

from anchorheal.decorator import get_caller_id


def test_caller_id_names_the_calling_file():
    assert get_caller_id(".price") == "test_caller_id.py:.price"


def test_user_code_in_a_folder_named_anchorheal_is_not_skipped(tmp_path):
    # Regression: frames used to be skipped whenever "anchorheal" appeared anywhere in the path.
    folder = tmp_path / "anchorheal-scrapers"
    folder.mkdir()
    script = folder / "shop_scraper.py"
    script.write_text(
        "from anchorheal.decorator import get_caller_id\n"
        "def run():\n"
        "    return get_caller_id('.price')\n"
    )
    spec = importlib.util.spec_from_file_location("shop_scraper", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.run() == "shop_scraper.py:.price"

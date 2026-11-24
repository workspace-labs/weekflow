"""Exercise the credential value rule through prepare on a disposable project."""

import unittest

import test_project_secrets as secrets


class SecretSettingValueTests(unittest.TestCase):
    setUp = secrets.ProjectSecretTests.setUp
    command = secrets.ProjectSecretTests.command
    succeed = secrets.ProjectSecretTests.succeed
    start = secrets.ProjectSecretTests.start
    prepare = secrets.ProjectSecretTests.prepare
    write_content = secrets.ProjectSecretTests.write_content
    settings = secrets.ProjectSecretTests.settings
    prepare_result = secrets.ProjectSecretTests.prepare_result
    refuse_prepare = secrets.ProjectSecretTests.refuse_prepare
    assert_secret_refusal = secrets.ProjectSecretTests.assert_secret_refusal

    def draft_with_setting(self, name, value, headline):
        self.settings(".env", f"{name}={value}\n")
        self.write_content(headline=headline)

    def test_auth_flags_and_short_descriptive_values_allow_ordinary_text(self):
        self.start()
        cases = (
            ("ENABLE_AUTH", "1", "Step 1 of the menu is ready"),
            ("USE_AUTH", "1", "Step 1 of the menu is ready"),
            ("REQUIRE_AUTH", "yes", "The client said yes"),
            ("DISABLE_AUTH", "0", "0 items are waiting"),
            ("ACCESS_TOKEN_EXPIRES_IN", "3600", "Open for 3600 seconds"),
            ("TOKEN_EXPIRE", "7", "Ready in 7 days"),
            ("AUTH_RETRIES", "3", "Ready in 3 days"),
            ("AUTH_TYPE", "basic", "The basic menu is ready"),
            ("AUTH_METHOD", "password", "The password screen is ready"),
            ("TOKEN_TYPE", "bearer", "The bearer note is ready"),
            ("CACHE_KEY_PREFIX", "menu", "The menu is ready"),
            ("PASSWORDLESS", "1", "Step 1 of the menu is ready"),
        )
        for name, value, headline in cases:
            with self.subTest(setting=name):
                self.draft_with_setting(name, value, headline)
                self.prepare()
                self.assertIn(headline, self.page.read_text(encoding="utf-8"))

    def test_common_flag_values_are_ignored_even_for_a_credential_noun(self):
        self.start()
        for value in ("0", "1", "YeS", "nO", "On", "oFF", "EnAbLeD", "DISABLED"):
            with self.subTest(value=value):
                headline = f"The draft note says {value} today."
                self.draft_with_setting("API_KEY", value, headline)
                self.prepare()
                self.assertIn(headline, self.page.read_text(encoding="utf-8"))
        headline = "The draft note says [ yes ] today."
        self.draft_with_setting("API_KEY", "' yes '", headline)
        self.prepare()
        self.assertIn(headline, self.page.read_text(encoding="utf-8"))

    def test_credential_nouns_still_compare_short_word_and_number_values(self):
        self.start()
        cases = (
            ("API_KEY", "q7x"),
            ("DB_PASSWORD", "1234"),
            ("DB_PASSWORD", "password"),
            ("PASSWORD_V2", "menu"),
            ("API_KEY_PROD", "abc123"),
            ("TOKEN_2", "q7x"),
        )
        for name, value in cases:
            with self.subTest(setting=name):
                # Keep the proof path free of the whole word under test.
                self.settings(".env", f"{name}={value}\n")
                self.write_content(headline=f"The draft note says {value} today.",
                                   finished=[{"text": "The shop is ready.", "source": "app/shop.txt"}])
                self.assert_secret_refusal(name, ".env", "headline", value)

    def test_matching_metadata_still_compares_mixed_or_eight_character_values(self):
        self.start()
        for name, value in (("TOKEN_TYPE", "m3nu"), ("SESSION_KEY_LENGTH", "12345678"),
                            ("TOKENIZER", "sandwich"),
                            ("AUTH_METHOD", "breadboard"), ("AUTH_METHOD", "m3nu")):
            with self.subTest(setting=name, value=value):
                self.draft_with_setting(name, value, f"The draft note says {value} today.")
                self.assert_secret_refusal(name, ".env", "headline", value)

    def test_auth_locators_allow_plain_values_and_keep_credentialed_urls_protected(self):
        self.start()
        for name in ("AUTH_URL", "AUTH_HOST", "AUTH_DOMAIN"):
            with self.subTest(setting=name):
                plain = "settings.invalid"
                headline = f"The project can use {plain} for sign-in."
                self.draft_with_setting(name, plain, headline)
                self.prepare()
                self.assertIn(headline, self.page.read_text(encoding="utf-8"))

                password = "q7x"
                url = f"bakery-db://owner:{password}@settings.invalid/db"
                self.draft_with_setting(name, url, f"The draft note says {password} today.")
                self.assert_secret_refusal(name, ".env", "headline", password, url)
                self.write_content(headline=f"The draft note says {url} today.")
                self.assert_secret_refusal(name, ".env", "headline", password, url)

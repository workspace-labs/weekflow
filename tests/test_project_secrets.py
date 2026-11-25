"""Check secret refusal through prepare on disposable project copies."""

from base64 import b64encode
import json
import os
import stat
import subprocess
import unittest

import test_weekflow as fixture
from test_arabic_documents import FORM as AR_FORM, PRD as AR_PRD, QUOTE as AR_QUOTE
from test_docs_meetings import FORM as EN_FORM, SOURCE as EN_SOURCE


class ProjectSecretTests(unittest.TestCase):
    setUp = fixture.WeekflowTests.setUp
    command = fixture.WeekflowTests.command
    succeed = fixture.WeekflowTests.succeed
    start = fixture.WeekflowTests.start
    prepare = fixture.WeekflowTests.prepare
    write_content = fixture.WeekflowTests.write_content

    def settings(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def prepare_result(self, setup=""):
        return self.command("prepare", "--content", str(self.content_path),
                            "--date", self.meeting_date, setup=setup)

    def refuse_prepare(self, setup=""):
        before = fixture.snapshot(self.scratch)
        result = self.prepare_result(setup)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(fixture.snapshot(self.scratch), before)
        return result.stdout + result.stderr

    def assert_secret_refusal(self, setting, name, field, *secrets):
        message = self.refuse_prepare()
        self.assertIn(setting, message)
        self.assertIn(name, message)
        self.assertIn(field, message)
        self.assertIn("remove", message.casefold())
        self.assertIn("prepare again", message.casefold())
        for secret in secrets:
            self.assertNotIn(secret, message)
            self.assertNotIn(json.dumps(secret)[1:-1], message)

    def meeting(self, mode, language):
        if language == "ar":
            form, prd = AR_FORM, AR_PRD
            approver = "الإصدار 2 · معتمد 2027-02-07 من العميل"
            draft = "الإصدار 1 · مسودة"
            sentence = AR_QUOTE.replace("{D-001}", "العميل")
            source = sentence + "\n\n- **المواعيد:** التسليم في 2027-03-12.\n"
            headline, title = "طلبات الاستلام", "الطلبات"
            day, attendee = "الأحد", "العميل"
        else:
            form, prd = EN_FORM, "# PRD: Corner Bakery\n"
            approver, draft = "v2 · Approved 2027-02-07 by the client", "v1 · Draft"
            sentence = "Orders wait in a basket."
            source = EN_SOURCE + "\n- **Dates:** Delivery by 2027-03-12.\n"
            headline, title = "Pickup orders", "How orders run"
            day, attendee = "Saturday", "the client"
        if mode == "docs":
            content = {"stage": 3, "decisions": [], "document": [
                {"title": title, "sentences": [{"text": sentence, "source": "docs/prd.md"}]},
            ]}
        else:
            content = {"finished": [{"text": title, "source": "app/menu.py"}]}
        content["headline"] = headline
        self.prd.write_text(prd + f"> {draft if mode == 'docs' else approver}\n\n" + source, encoding="utf-8")
        (self.project / "docs/meeting-form.md").write_text(form, encoding="utf-8")
        self.succeed("start", "--language", language, "--meeting-day", day)
        project_row = self.weekly / "project.json"
        self.assertEqual(json.loads(project_row.read_bytes())["mode"], mode)
        return content, attendee

    def write_draft(self, data):
        self.content_path.parent.mkdir(parents=True, exist_ok=True)
        self.content_path.write_text(json.dumps(data), encoding="utf-8")

    def check_meeting(self, mode, language):
        content, _ = self.meeting(mode, language)
        secret = "رمز-التجربة-الخاص" if language == "ar" else "fixture-secret-for-headline"
        self.settings("config/deep/.env.local", f"ACCOUNT_PASSWORD={secret}\n")
        self.write_draft(dict(content, headline=f"{content['headline']}: {secret}"))
        self.assert_secret_refusal("ACCOUNT_PASSWORD", "config/deep/.env.local", "headline", secret)
        self.write_draft(content)
        self.prepare()

    def test_english_docs_meeting_refuses_secret_before_writing(self):
        self.check_meeting("docs", "en")

    def test_english_build_meeting_refuses_secret_before_writing(self):
        self.check_meeting("build", "en")

    def test_arabic_docs_meeting_refuses_secret_before_writing(self):
        self.check_meeting("docs", "ar")

    def test_arabic_build_meeting_refuses_secret_before_writing(self):
        self.check_meeting("build", "ar")

    def test_decoded_secret_refuses_before_writing_any_file(self):
        self.start()
        secret = "fixture-secret-é-17"
        self.settings(".env", f"\ufeff  # settings for the fixture\n\n export API_KEY='{secret}' # comment\n")
        self.write_content(headline=f"The menu note [{secret}] is ready.")
        self.assertNotIn(secret, self.content_path.read_text(encoding="utf-8"))
        self.assert_secret_refusal("API_KEY", ".env", "headline", secret)

    def test_secret_setting_names_are_matched_without_case(self):
        self.start()
        names = ("PaSsWoRd", "DB_PASSWD", "DB_PWD", "SERVICE_SECRET", "service_token",
                 "LOGIN_CREDENTIAL", "LOGIN_AUTH", "API_KEY", "APIKEY", "PRIVATE_KEY", "ACCESS_KEY")
        values = {name: f"fixture-settings-{index:02d}" for index, name in enumerate(names)}
        env = "settings/.env.sample.local"
        self.settings(env, "".join(f"{name}={value} # ignored\n" for name, value in values.items()))
        for name, value in values.items():
            with self.subTest(setting=name):
                self.write_content(headline=f"The note includes {value}.")
                self.assert_secret_refusal(name, env, "headline", *values.values())

    def check_review_secret_names(self, language):
        content, _ = self.meeting("build", language)
        names = ("clientSecret", "dbPassword", "BUNNEV_CREDENTIALS", "API_TOKENS", "CLIENT_SECRETS",
                 "DBPASSWORD", "AUTHTOKEN", "ACCESSKEY", "cLiEnTsEcReT", "aCcEsSkEy", "clientAPIKEYProd",
                 "API_KEY", "APIKEY", "PRIVATE_KEY", "ACCESS_KEY", "SECRET_KEY",
                 "AUTH_TOKEN", "API_KEY_PROD", "PASSWORD_V2", "TOKEN_2")
        for index, name in enumerate(names, start=10):
            with self.subTest(setting=name, language=language):
                value = f"رمز{index}" if language == "ar" else f"zxc{index}q"
                self.settings(".env", f"{name}={value}\n")
                self.write_draft(dict(content, headline=f"{content['headline']} ({value})"))
                self.assert_secret_refusal(name, ".env", "headline", value)
                embedded = f"ب{value}ج" if language == "ar" else f"pre{value}post"
                self.write_draft(dict(content, headline=f"{content['headline']} ({embedded})"))
                self.prepare()

    def test_review_secret_names_protect_short_values_as_words_in_english(self):
        self.check_review_secret_names("en")

    def test_review_secret_names_protect_short_values_as_words_in_arabic(self):
        self.check_review_secret_names("ar")

    def check_review_descriptive_settings(self, language):
        content, _ = self.meeting("docs", language)
        examples = (
            ("AUTH_ENABLED", "1", "Step 1 of the menu is ready", "الخطوة 1 من القائمة جاهزة"),
            ("TOKEN_TTL_DAYS", "7", "Ready in 7 days", "سيجهز خلال 7 أيام"),
            ("SESSION_KEY_LENGTH", "32", "All 32 menu items are ready", "الأصناف كلها جاهزة وعددها 32"),
            ("AUTH_REQUIRED", "yes", "The client said yes", "قال العميل نعم"),
        )
        if language == "ar":
            examples = (*examples[:-1], ("AUTH_REQUIRED", "نعم", examples[-1][2], examples[-1][3]))
        for name, value, english, arabic in examples:
            with self.subTest(setting=name, language=language):
                self.settings(".env", f"{name}={value}\n")
                self.write_draft(dict(content, headline=arabic if language == "ar" else english))
                self.prepare()

    def test_review_descriptive_flags_and_limits_allow_english_meeting_words(self):
        self.check_review_descriptive_settings("en")

    def test_review_descriptive_flags_and_limits_allow_arabic_meeting_words(self):
        self.check_review_descriptive_settings("ar")

    def test_review_descriptive_suffixes_compare_long_and_mixed_values(self):
        self.start()
        descriptors = ("ENABLED", "DISABLED", "REQUIRED", "TTL", "DAYS", "HOURS", "MINUTES",
                       "SECONDS", "EXPIRY", "EXPIRES", "TIMEOUT", "LENGTH", "SIZE", "COUNT",
                       "LIMIT", "PORT", "HOST", "DOMAIN", "URL", "ALGORITHM", "MODE", "PROVIDER", "ISSUER")
        names = (*(f"SESSION_TOKEN_{suffix}" for suffix in descriptors),
                 "authEnabled", "ToKeNtTlDaYs", "SESSIONTOKENLENGTH")
        for index, name in enumerate(names, start=10):
            with self.subTest(setting=name):
                plain = str(index) if index % 2 else "plain"
                self.settings(".env", f"{name}={plain}\n")
                self.write_content(headline=f"The menu note includes [{plain}].")
                self.prepare()
                for value in (f"fixture-setting-detail-{index}", f"z{index}"):
                    with self.subTest(value_kind="long" if len(value) >= 8 else "mixed"):
                        self.settings(".env", f"{name}={value}\n")
                        self.write_content(headline=f"The menu note includes [{value}].")
                        self.assert_secret_refusal(name, ".env", "headline", value)

    def test_review_ordinary_setting_names_are_allowed_with_long_values(self):
        self.start()
        names = ("AUTHOR", "KEYBOARD", "MONKEY", "AUTHOR_NAME", "KEYWORDS", "COMPASS",
                 "PASSENGER", "SECRETARY_NAME")
        for index, name in enumerate(names, start=36):
            with self.subTest(setting=name):
                value = f"fixture-setting-detail-{index}"
                self.settings(".env", f"{name}={value}\n")
                self.write_content(headline=f"The menu note includes {value}.")
                self.prepare()

    def test_review_numbered_joined_and_pass_setting_names_refuse_short_values(self):
        self.start()
        names = ("API_KEY2", "DB_PWD2", "BAKERY_KEY1", "DBPWD", "BAKERYPWD", "SIGNINGKEY",
                 "ENCRYPTIONKEY", "MASTERKEY", "DB_PASS", "SMTP_PASS", "MAIL_PASS", "DB_PASSPHRASE")
        for name in names:
            with self.subTest(setting=name):
                value = "cedar"
                self.settings(".env", f"{name}={value}\n")
                self.write_content(headline=f"The menu note includes [{value}].")
                self.assert_secret_refusal(name, ".env", "headline", value)

    def test_review_locator_suffixes_still_check_credential_names(self):
        self.start()
        names = ("SECRET_URL", "WEBHOOK_SECRET_URL", "secretUrl", "TOKEN_URL", "API_KEY_HOST",
                 "DB_PASS_DOMAIN", "LOGIN_CREDENTIALS_DOMAIN")
        for index, name in enumerate(names, start=10):
            with self.subTest(setting=name):
                value = f"fixture-location-value-{index}"
                self.settings(".env", f"{name}={value}\n")
                self.write_content(headline=f"The menu note includes [{value}].")
                self.assert_secret_refusal(name, ".env", "headline", value)

    def test_review_short_url_password_equal_to_username_allows_headline_and_source_in_english(self):
        self.start()
        for login in ("app:app", "%61pp:%61%70%70"):
            with self.subTest(login=login):
                url = f"bakery-db://{login}@localhost:5432/app"
                self.settings(".env", f"DATABASE_URL={url}\n")
                self.write_content(headline="The app is ready.")
                self.prepare()
                self.write_content(headline=f"Keep {url} out of the note.")
                self.assert_secret_refusal("DATABASE_URL", ".env", "headline", url)

    def test_review_url_still_refuses_distinct_short_password_and_descriptive_setting(self):
        self.start()
        url = "bakery-db://seller:menu@host/db"
        self.settings(".env", f"AUTH_PROVIDER={url}\n")
        # The original fixture path also contains menu. Use a clean proof path
        # here so it is the headline that triggers the refusal.
        finished = [{"text": "The shop is ready.", "source": "app/shop.txt"}]
        self.write_content(headline="The menus are ready.", finished=finished)
        self.prepare()
        self.write_content(headline="The menu is ready.", finished=finished)
        self.assert_secret_refusal("AUTH_PROVIDER", ".env", "headline", "menu", url)
        self.write_content(headline=f"Keep {url} out of the note.", finished=finished)
        self.assert_secret_refusal("AUTH_PROVIDER", ".env", "headline", url)
        for user, password in (("Menu", "menu"), ("fixture-login", "fixture-login")):
            with self.subTest(user=user):
                url = f"bakery-db://{user}:{password}@host/db"
                self.settings(".env", f"DATABASE_URL={url}\n")
                self.write_content(headline=f"The draft contains [{password}].", finished=finished)
                self.assert_secret_refusal("DATABASE_URL", ".env", "headline", password, url)

    def test_review_repeated_short_arabic_url_password_allows_headline(self):
        content, _ = self.meeting("build", "ar")
        url = "bakery-db://خبز:خبز@host/db"
        self.settings(".env", f"DATABASE_URL={url}\n")
        self.write_draft(dict(content, headline="الخبز جاهز مع خبز إضافي"))
        self.prepare()
        self.write_draft(dict(content, headline=f"عنوان نقطة الاتصال {url}"))
        self.assert_secret_refusal("DATABASE_URL", ".env", "headline", url)

    def test_review_distinct_short_arabic_url_password_is_a_secret(self):
        content, _ = self.meeting("build", "ar")
        url = "bakery-db://مالك:خبز@host/db"
        self.settings(".env", f"AUTH_PROVIDER={url}\n")
        self.write_draft(dict(content, headline="هذا الخبز جاهز"))
        self.prepare()
        self.write_draft(dict(content, headline="تم تحضير خبز وطلبات"))
        self.assert_secret_refusal("AUTH_PROVIDER", ".env", "headline", "خبز", url)

    def test_double_quoted_secret_matches_after_one_line_normalisation(self):
        self.start()
        value = "fixture # white code"
        self.settings(".env", f'LINE_SECRET="{value}" # this is the comment\n')
        original = value.replace("white code", "white\t\n code")
        self.write_content(headline=f"The note includes {original}.")
        self.assert_secret_refusal("LINE_SECRET", ".env", "headline", value, original)

    def test_short_values_require_word_boundaries_and_eight_characters_do_not(self):
        self.start()
        short, long = "q7xk93z", "q8xk93pz"
        self.settings(".env", f"LOGIN_PWD={short}\nSESSION_TOKEN={long}\n")
        self.write_content(headline=f"Allow the larger word pre{short}post to appear.")
        self.prepare()
        self.write_content(headline=f"Do not keep [{short}] in the note.")
        self.assert_secret_refusal("LOGIN_PWD", ".env", "headline", short, long)
        self.write_content(headline=f"Do not keep pre{long}post in the note.")
        self.assert_secret_refusal("SESSION_TOKEN", ".env", "headline", short, long)

    def test_url_and_password_count_under_an_ordinary_setting_name(self):
        self.start()
        password = "fixture-url-9w47"
        url = f"scheme://owner:{password}@settings.invalid/list"
        encoded_password = "fixture-url%409x48"
        decoded_password = "fixture-url@9x48"
        encoded_url = f"scheme://owner:{encoded_password}@settings.invalid/list"
        # The placeholder password is ignored on its own. The URL still contains userinfo.
        placeholder_url = "scheme://owner:example@settings.invalid/list"
        self.settings(".env.development", f"ROUTE={url}\nFALLBACK_ROUTE='{placeholder_url}'\n"
                      f"ENCODED_ROUTE={encoded_url}\n")
        for name, value in (("ROUTE", password), ("ROUTE", url), ("FALLBACK_ROUTE", placeholder_url),
                            ("ENCODED_ROUTE", encoded_password), ("ENCODED_ROUTE", decoded_password)):
            with self.subTest(setting=name, url=value.startswith("scheme:")):
                self.write_content(headline=f"The draft contains {value}.")
                self.assert_secret_refusal(name, ".env.development", "headline",
                                           password, url, placeholder_url, encoded_password, decoded_password)

    def test_secret_in_nested_key_is_refused_without_printing_the_key(self):
        self.start()
        value = "fixture-json-key-é"
        self.settings(".env", f"LOCAL_KEY={value}\n")
        self.write_content(notes=[{value: "The note does not contain the value."}])
        self.assert_secret_refusal("LOCAL_KEY", ".env", "notes", value)

    def test_secret_in_an_earlier_duplicate_json_value_is_still_refused(self):
        self.start()
        value = "fixture-duplicate-é-key"
        self.settings(".env", f"LOCAL_KEY={value}\n")
        clean = self.write_content()
        clean_json = self.content_path.read_text(encoding="utf-8")
        first_value = json.dumps(f"The draft contains {value}.")
        duplicate = '{"headline": ' + first_value + ', ' + clean_json[1:]
        self.assertEqual(json.loads(duplicate), clean)
        self.content_path.write_text(duplicate, encoding="utf-8")
        self.assert_secret_refusal("LOCAL_KEY", ".env", "headline", value)

    def test_secret_in_source_path_is_refused_before_checking_the_source(self):
        self.start()
        value = "fixture-source-key"
        self.settings(".env", f"LOCAL_KEY={value}\n")
        self.write_content(finished=[{"text": "The menu now opens.", "source": f"app/{value}.py"}])
        self.assert_secret_refusal("LOCAL_KEY", ".env", "source", value)

    def test_saved_source_spelling_is_checked_before_backslashes_become_slashes(self):
        self.start()
        value = "app/menu.py"
        self.settings(".env", f"LOCAL_KEY={value}\n")
        self.write_content(finished=[{"text": "The menu now opens.", "source": r"app\menu.py"}])
        self.assert_secret_refusal("LOCAL_KEY", ".env", "source", value)

    def test_placeholders_comments_and_nearby_setting_names_are_allowed(self):
        self.start()
        self.settings(".env", """
        # SESSION_TOKEN=fixture-comment-value
        FIRST_KEY=ChAnGeMe
        SECOND_KEY="example"
        THIRD_KEY='none'
        FOURTH_KEY=NULL
        FIFTH_KEY=true
        SIXTH_KEY=FALSE
        SEVENTH_KEY=
        EIGHTH_KEY=""
        PUBLIC_LABEL=fixture-public-label  # fixture-comment-value
        MONKEY=fixture-monkey-label
        AUTHOR=fixture-author-label
        """)
        headline = ("ChAnGeMe example none NULL true FALSE fixture-comment-value "
                    "fixture-public-label fixture-monkey-label fixture-author-label")
        self.write_content(headline=headline)
        self.prepare()
        self.assertIn(headline, self.page.read_text(encoding="utf-8"))

    def test_example_files_dependencies_virtual_envs_and_weekly_outputs_are_skipped(self):
        self.start()
        files = (
            ".git/.env", "tools/node_modules/.env.local", "deep/.venv/.env",
            "deep/venv/.env.local", "tools/local-python/.env",
            "docs/weekly/.env", "docs/weekly/pages/.env.local",
            ".env.example", "settings/.env.sample", "settings/deep/.env.template",
        )
        self.settings("tools/local-python/pyvenv.cfg", "include-system-site-packages = false\n")
        values = [f"fixture-ignored-{index:02d}" for index, _ in enumerate(files)]
        for path, value in zip(files, values):
            self.settings(path, f"SESSION_TOKEN={value}\n")
        headline = " ".join(values)
        self.write_content(headline=headline)
        self.prepare()
        self.assertIn(headline, self.page.read_text(encoding="utf-8"))

    def test_outside_folder_link_is_skipped_without_reading_its_settings(self):
        self.start()
        value = "fixture-outside-folder"
        outside = self.scratch / "outside"
        outside.mkdir()
        (outside / ".env").write_text(f"SESSION_TOKEN={value}\n", encoding="utf-8")
        try:
            (self.project / "linked-settings").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("This system does not allow test symlinks.")
        self.write_content(headline=f"The draft can contain {value}.")
        self.prepare()
        self.assertIn(value, self.page.read_text(encoding="utf-8"))

    def test_settings_file_link_staying_inside_the_project_is_checked(self):
        self.start()
        for suffix, name in (("relative", "RELATIVE_TOKEN"), ("absolute", "ABSOLUTE_TOKEN")):
            with self.subTest(link=suffix):
                value = f"fixture-inside-{suffix}-link"
                target = self.settings(f"configuration/{suffix}.txt", f"{name}={value}\n")
                env = f".env.{suffix}"
                destination = target.relative_to(self.project) if suffix == "relative" else target
                try:
                    (self.project / env).symlink_to(destination)
                except (OSError, NotImplementedError):
                    self.skipTest("This system does not allow test symlinks.")
                self.write_content(headline=f"The draft contains {value}.")
                self.assert_secret_refusal(name, env, "headline", value)

    def test_settings_file_link_leaving_the_project_refuses_without_reading_target(self):
        self.start()
        value = "fixture-outside-file"
        outside = self.scratch / "local.env"
        outside.write_text(f"SESSION_TOKEN={value}\n", encoding="utf-8")
        try:
            (self.project / ".env.local").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("This system does not allow test symlinks.")
        self.write_content()
        message = self.refuse_prepare()
        self.assertIn(".env.local", message)
        self.assertNotIn(value, message)
        self.assertNotIn(str(outside), message)

    def test_settings_file_with_invalid_text_refuses_even_for_a_clean_draft(self):
        self.start()
        settings = self.settings("config/.env", "")
        settings.write_bytes(b"\xff\xfe\xfd")
        self.write_content()
        self.assertIn("config/.env", self.refuse_prepare())

    def test_unreadable_settings_file_refuses_even_for_a_clean_draft(self):
        self.start()
        value = "fixture-unreadable-value"
        env = self.settings("config/.env.local", f"SECRET={value}\n")
        self.write_content()
        before = fixture.snapshot(self.scratch)
        mode = stat.S_IMODE(env.stat().st_mode)
        env.chmod(0)
        try:
            denied = stat.S_IMODE(env.stat().st_mode)
            setup = ""
            if os.access(env, os.R_OK):
                # Some accounts and platforms can read a file with its mode set to zero.
                setup = f"""
from pathlib import Path

read_bytes = Path.read_bytes

def deny_settings(path):
    if path == Path({str(env.resolve())!r}):
        raise PermissionError("Test denied access")
    return read_bytes(path)

Path.read_bytes = deny_settings
"""
            result = self.prepare_result(setup)
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), denied)
        finally:
            env.chmod(mode)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("config/.env.local", result.stderr)
        self.assertNotIn(value, result.stderr)
        self.assertEqual(fixture.snapshot(self.scratch), before)

    def test_secret_refusal_leaves_an_interrupted_transaction_untouched(self):
        self.start()
        value = "fixture-journal-check"
        self.settings(".env", f"SECRET={value}\n")
        self.write_content(headline=f"The draft contains {value}.")
        # The pending transaction restores changes and removes its journal on the next valid command.
        earlier = b64encode(b"[]\n").decode("ascii")
        journal = self.weekly / ".weekflow-undo.json"
        journal.write_text(json.dumps([{"path": "docs/weekly/changes.json", "data": earlier}]),
                           encoding="utf-8")
        self.assert_secret_refusal("SECRET", ".env", "headline", value)
        self.assertTrue(journal.is_file())
        self.write_content()
        self.prepare()
        self.assertFalse(journal.exists())
        self.assertEqual((self.weekly / "changes.json").read_bytes(), b"[]\n")

    def test_secret_in_pending_draft_replacement_is_checked_before_recovery_writes_it(self):
        self.start()
        value = "fixture-pending-draft-key"
        self.settings(".env", f"SECRET={value}\n")
        clean = self.write_content()
        restored = json.dumps(dict(clean, headline=f"The draft contains {value}.")).encode("utf-8")
        journal = self.weekly / ".weekflow-undo.json"
        journal.write_text(json.dumps([{
            "path": self.content_path.relative_to(self.project).as_posix(),
            "data": b64encode(restored).decode("ascii"),
        }]), encoding="utf-8")
        self.assert_secret_refusal("SECRET", ".env", "headline", value)
        self.assertTrue(journal.is_file())

    def check_clean_outputs(self, *, decode_pdf):
        secrets = ("fixture-é-key-48", "رمز-التجربة-الخاص", "q7xk93z", "fixture-url-9w47")
        url = f"scheme://owner:{secrets[-1]}@settings.invalid/list"
        self.settings(".env", f"API_KEY='{secrets[0]}'\nTOKEN={secrets[1]}\n"
                      f"LOGIN_PWD={secrets[2]}\nROUTE={url}\n")
        before = fixture.snapshot(self.project)
        output = self.start()
        clean = self.write_content()
        statements = [
            ("API_KEY", secrets[0]), ("TOKEN", secrets[1]), ("LOGIN_PWD", secrets[2]),
            ("ROUTE", secrets[-1]), ("ROUTE", url),
        ]
        for setting, value in statements:
            self.write_content(headline=f"The draft contains [{value}].")
            self.assert_secret_refusal(setting, ".env", "headline", *secrets, url)
        self.write_draft(clean)
        output += self.prepare()
        output += self.succeed("confirm")
        recorded = self.command("record", "--answer", "--attendee", "the client",
                                setup=fixture.cli_date_setup(self.meeting_date))
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        output += recorded.stdout + recorded.stderr
        result = self.command("client-copy", setup="" if decode_pdf else fixture.TEST_PDF_RENDERER)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output += result.stdout + result.stderr
        output += self.succeed("lock")
        # The draft was written by the test. All other changes were written by WeekFlow.
        draft = self.content_path.relative_to(self.project).as_posix()
        written = {
            name: data for name, data in fixture.snapshot(self.project).items()
            if isinstance(data, bytes) and data != before.get(name) and name != draft
        }
        self.assertTrue({"docs/weekly/project.json", "docs/weekly/weeks/week-3.json",
                         "docs/weekly/pages/week-3-content.json", "docs/weekly/pages/week-3.html",
                         "docs/weekly/pages/week-3.pdf"} <= written.keys())
        checked = dict(written, output=output.encode("utf-8"))
        if decode_pdf:
            pdf_text = subprocess.check_output(["pdftotext", "-enc", "UTF-8", str(self.client_page), "-"], timeout=15)
            self.assertIn(b"The bread menu is ready", pdf_text)
            checked["decoded PDF"] = pdf_text
        for name, data in checked.items():
            with self.subTest(output=name):
                for value in (*secrets, url):
                    self.assertNotIn(value.encode("utf-8"), data)
                    self.assertNotIn(json.dumps(value)[1:-1].encode("ascii"), data)

    def test_cleaned_run_leaves_no_secret_in_any_written_file(self):
        self.check_clean_outputs(decode_pdf=False)

    @unittest.skipUnless(fixture.PDF_TEXT, "ReportLab and pdftotext are required for decoded PDF checks.")
    def test_cleaned_run_leaves_no_secret_in_rendered_pdf(self):
        self.check_clean_outputs(decode_pdf=True)

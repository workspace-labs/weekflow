# 033. Identify secret settings in local environment files

## Context

The security rules require preparation to refuse a draft that contains a project secret. The approved documents leave the file format, classification and comparison rules to the build.

## Options

- Match all project settings. This covers unfamiliar naming conventions and would also refuse ordinary public values.
- Use the name and value together. Credential names and credentialed URLs stay in scope, and short descriptive values can appear in ordinary meeting text.

## Decision

Read project-local `.env` and `.env.*` files. Skip the three example variants, Git and dependency directories, virtual environments, and `docs/weekly/`. Skip directory symlinks during discovery. A discovered settings-file symlink must resolve within the project throughout its chain. A permission, decoding or quoting error in a settings file stops preparation.

Compare names without regard to case, using underscore and camel-case word edges. Password, passwd, passphrase, secret, token and credential can also appear inside joined names. Key and pwd can end a joined name or precede a number. Pass needs a word edge. Plurals and known joined key names count. Author, keyboard, keywords, monkey, compass, passenger and secretary stay ordinary words. A final URL, host or domain excludes a name whose only credential marker is auth. Names with another credential marker are still eligible.

Ignore empty values, common placeholders, and the flag values 0, 1, yes, no, on, off, enabled and disabled in any letter case. For an eligible name, find its last meaningful word after ignoring prod, dev, staging, test, local, versions such as v2, and numbers. A credential noun at the end keeps the value eligible at any length. Other endings exempt values under eight characters made entirely of letters or entirely of digits. Longer or mixed values remain eligible. The value password in an auth-only method setting names a login method and is also exempt.

A credentialed URL counts under any setting name. Check the whole URL and the password, including its decoded spelling. If the decoded password is shorter than eight characters and exactly equals the decoded username, check the whole URL alone for that setting.

Check decoded JSON keys and values, including repeated entries. Compare the original and one-line forms and the project-relative spelling of source paths used in saved content. Values of eight characters or more match as substrings. Shorter values use Unicode word boundaries. A refusal uses a field position when the field name itself contains a secret.

## Consequences

The check works without reading environment variables from the running shell or interpreting dotenv values as commands. A credential under an unrecognised name can escape the check. A long ordinary value under a matching name such as `TOKENIZER` can be refused.

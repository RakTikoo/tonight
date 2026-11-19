# Contributing

Thanks for looking. tonight is a small, single-purpose tool; these
house rules keep changes easy to review.

## Run the tests

```console
$ python3 run_tests.py
```

All tests must pass before a change is considered. Add tests in `tests/`
for any new behaviour.

## House rules

- Keep the tool single-purpose and fully offline: no network lookups
  (no site-name or time-zone databases). Do not add a dependency
  without raising it in an issue first.
- The README's Limits section is a promise. If a change alters a
  documented limit or behaviour, update the README in the same pull
  request — and SKILL.md too if the CLI, its flags or its exit codes
  changed.
- Plain words in docs and messages. No marketing language.

## Claiming an issue

Comment on the issue saying you are taking it, then open a pull request
that mentions the issue number.

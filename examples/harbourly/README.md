# Example project: Harbourly (fictional)

Harbourly is an invented company that sells booking software to boat-hire businesses. It exists
only to show what a configured tracker looks like and to drive the public test suite. Every
domain uses the reserved `.example` TLD, and the people and figures are made up.

| File | What it shows |
|---|---|
| [example.env](example.env) | A filled-in configuration: domain, two markets (UK, US), London timezone, custom email subject. |
| [tracker_example.csv](tracker_example.csv) | The tracker tab after two weekly runs. Row 1 holds dates, row 2 the market codes, and each keyword row holds positions. `-` means not in the top 100. `64/blog` is a hand-typed note (only the leading number is used). The last row has no volume, so it is skipped. |
| [sample_oxylabs_response.json](sample_oxylabs_response.json) | A trimmed Oxylabs Google search response. Harbourly is 3rd in `organic`. The `paid` result is ignored. |

To try the tracker with your own site, start from the blank
[templates/tracker_template.csv](../../templates/tracker_template.csv) and the root
[.env.example](../../.env.example) instead.

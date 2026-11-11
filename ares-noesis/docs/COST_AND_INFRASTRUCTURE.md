# Cost and infrastructure

Development uses the existing hosted Work sandbox, a Python virtual environment, workspace storage and the connected GitHub repository. The backend defaults to offline operation. The packaged application has no automatic paid model client, S3 storage or external graph writes. No billing settings, trials, credits or payment methods were used for this build.

| Option | Decision | Constraints |
| --- | --- | --- |
| Hosted Work workspace | Used for development and testing | Temporary workspace and compute, no guaranteed uptime or public endpoint |
| GitHub repository | Used for persistent source | Public source only |
| GitHub Actions | Workflow permits only the standard runner for a public repository | No larger runners, caches or uploaded artifacts. GitHub usage and job limits still apply |
| Render Free | Unused | Idle spin-down, ephemeral disk, expiring free Postgres, and documented bandwidth overage behavior |
| Railway and other cloud services | Unused | The account-specific nontrial and no-overage conditions were not established |
| External inference, GPU, managed database | Unused | No compliant resources selected |

Official references: [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage), [GitHub Actions billing details](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Render Free limits](https://render.com/docs/free).

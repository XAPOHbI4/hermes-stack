# Hermes Forge profile integration

Hermes Forge is installed for this profile as a local-first improvement loop.

Use it when you need evidence-driven self-improvement without silent mutation:

```bash
bin/forge-improve
```

This runs `hermes-forge improve --mode read-only` for the current profile and writes artifacts outside the scanned Hermes home, under:

```text
/root/hermes/reports/forge/profiles/<profile>/<UTC timestamp>/
/root/hermes/reports/forge/profiles/<profile>/latest -> latest run
```

Safety contract:
- read-only improve scans metadata/log categories/session aggregates only;
- report must show evidence, hypothesis, experiment and next safe step;
- `diff-preview` is preview-only;
- `apply` requires explicit approval and only supports the bounded `skill_frontmatter_metadata_v1` executor;
- do not apply generated candidates automatically.

Shared CLI:

```bash
hermes-forge doctor
hermes-forge capabilities
hermes-forge improve --mode read-only --hermes-home /root/.hermes --all-profiles --out /root/hermes/reports/forge/all-profiles/<run>
```

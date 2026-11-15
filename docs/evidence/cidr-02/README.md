# CIDR-02 - onboarding destination evidence

Baseline: `573e096`. Local fixtures only; no live vendor/customer credential or production deployment. [Behavior, commands, assumptions, failure analysis and rollout](../../ONBOARDING_SUGGESTIONS.md).

- [Full backend suite](logs/backend-full.txt): 624 passed. [Final backend release checks](logs/backend-release.txt): clean lint/format/schema/migration checks and 22 affected cases passed after additive site/ID metadata.
- [Final frontend gates](logs/frontend-final.txt): types, lint, 94 tests and production build passed.
- [Final full browser suite](logs/browser-final.txt): **43 passed (3.6 minutes)** on fresh fixtures, including the updated onboarding workflow.
- Settled [desktop](onboarding-group-1440.png) and [phone](onboarding-group-390.png) captures; [visual observations](visual.json) and [terminal output](logs/visual.txt): zero JavaScript errors or page overflow, one filtered device row. Both images inspected. Capture reused the approved fixture state, waited for network idle and one filtered table row, and made no writes. The browser capture also explicitly waits for one filtered row after debounce.
- Corrected early failures: [old approved-only expectations](logs/backend-legacy-expectations.txt), [fixture device count](logs/backend-focused-initial.txt), [test-only types](logs/frontend-types-initial.txt).
- [First browser attempt](logs/browser-first-run.txt): 41 passed, two failed; includes an 11.4-hour reported gap during session checking and duplicate display-name suggestion controls. Final controls show site/stable group ID, and the final run uses a fresh database without relaxed timeouts.

Screenshots are captured by the actual administrator workflow after a different administrator approves a destination CIDR. The group is searched to one device, so the approved and weaker evidence remain readable. The browser also checks that the device still belongs to its original group and that selecting a destination only fills a proposal form.

Full changed path list: changed-files.txt. Artifact hashes: manifest.sha256. This evidence does not close Docker/live/SSO/restore/security/production acceptance gates.

# Contributing

Thank you for your interest in contributing to this project! We appreciate all contributions, whether they are bug reports, feature requests, documentation improvements, or code changes.

Please take a moment to read these guidelines before submitting an issue or pull request.

## Code of Conduct

By participating in this project, you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

Instances of abusive, harassing, or otherwise unacceptable behavior may be reported to the community leaders responsible for enforcement at **[miguelobx34@gmail.com](mailto:miguelobx34@gmail.com)**.

All complaints will be reviewed and investigated promptly and fairly.

All community leaders are obligated to respect the privacy and security of anyone reporting an incident.

## How to Contribute

There are several ways you can contribute to the project:

* Report bugs.
* Suggest new features or improvements.
* Improve documentation.
* Fix existing issues.
* Submit new tests.
* Review pull requests.
* Improve code quality or performance.

## Reporting Bugs

Before reporting a bug, please check the existing issues to make sure it has not already been reported.

When opening a bug report, provide as much relevant information as possible, including:

* A clear and descriptive title.
* A description of the problem.
* Steps to reproduce the issue.
* Expected behavior.
* Actual behavior.
* Relevant logs or error messages.
* Your operating system and environment.
* The project version or commit where the issue occurs.

If possible, include a minimal reproducible example.

Please do not include passwords, API keys, access tokens, personal information, or other sensitive data in an issue.

## Suggesting Features

Feature requests are welcome.

Before submitting a feature request, please check the existing issues and discussions to see if a similar request already exists.

A good feature request should include:

* A clear description of the proposed feature.
* The problem it would solve.
* Why the feature would be useful.
* Examples of how it could be used.
* Any alternative solutions you have considered.

## Pull Requests

Before submitting a pull request:

1. Check the existing issues and pull requests.
2. Make sure your changes are focused on a specific issue or improvement.
3. Keep changes as small and focused as reasonably possible.
4. Add or update tests when appropriate.
5. Update the documentation when necessary.
6. Make sure the project builds successfully.
7. Make sure all tests pass.
8. Review your changes before submitting the pull request.

Pull requests should clearly describe:

* What has been changed.
* Why the change was necessary.
* How the change was implemented.
* Any relevant issue or discussion.

If your pull request fixes an existing issue, reference it in the description using the appropriate issue number.

## Development Workflow

A typical contribution workflow is:

```bash
git clone <repository-url>
cd <repository-directory>

git checkout -b feature/my-feature
```

Make your changes, then verify the project:

```bash
git status
git diff
```

Run the project's tests and build before committing.

Once your changes are ready:

```bash
git add .
git commit -m "Add my feature"
git push origin feature/my-feature
```

Then open a pull request against the project's main development branch.

## Branches

Please use descriptive branch names.

Recommended prefixes include:

* `feature/` — New functionality.
* `fix/` — Bug fixes.
* `docs/` — Documentation changes.
* `refactor/` — Code refactoring.
* `test/` — Test-related changes.
* `chore/` — Maintenance tasks.

Examples:

```text
feature/add-user-authentication
fix/connection-timeout
docs/update-installation
refactor/improve-logging
test/add-api-tests
```

## Commit Messages

Please write clear and concise commit messages.

Prefer messages that describe what the commit does rather than what you did.

Good examples:

```text
Add support for XYZ
Fix connection timeout handling
Update installation documentation
Improve error handling
Add tests for authentication
```

Avoid vague messages such as:

```text
Update
Changes
Fix
Stuff
Work
```

## Code Style

Please follow the existing coding conventions used by the project.

When adding new code:

* Keep the implementation simple and readable.
* Avoid unnecessary complexity.
* Use meaningful names.
* Remove unused code and imports.
* Add comments only when they provide useful context.
* Avoid committing debug code or temporary files.
* Follow the formatting and linting rules configured by the project.

## Tests

New functionality should include appropriate tests whenever possible.

Bug fixes should preferably include a test that reproduces the problem and verifies that it has been fixed.

Before submitting a pull request, make sure that:

* Existing tests pass.
* New tests pass.
* No unrelated tests are broken.
* The project builds successfully.

## Documentation

Documentation improvements are always welcome.

When changing functionality, configuration, APIs, commands, or behavior, please update the relevant documentation.

Documentation should be:

* Clear and concise.
* Accurate.
* Easy to understand.
* Consistent with the existing project documentation.

## Issues

Please use the appropriate issue template when one is available.

Do not use issues for general support questions if the project provides another support channel.

Security vulnerabilities should **not** be reported through public issues. Please follow the project's security reporting process instead.

## Security

Please do not publicly disclose security vulnerabilities before they have been reviewed by the project maintainers.

If you discover a security vulnerability, contact the project maintainers privately using the security contact provided by the project.

Do not include sensitive information such as credentials, private keys, access tokens, or personal data in public issues or pull requests.

## Review Process

All pull requests are subject to review.

Maintainers may request changes before a pull request is merged.

Reviews may consider:

* Correctness.
* Security.
* Performance.
* Maintainability.
* Test coverage.
* Documentation.
* Compatibility with the project's goals.

Contributors are expected to respond constructively to review feedback.

## Licensing

By contributing to this project, you agree that your contributions may be distributed under the same license as the project, unless otherwise stated.

Please make sure that you have the right to submit any code, documentation, images, or other material included in your contribution.

## Questions

If you are unsure about how to contribute, open an issue or contact the project maintainers.

Thank you for contributing!

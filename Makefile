# One gate, run the same way locally and in CI (.github/workflows/ci.yml). Tools: requirements-dev.txt.
SKILL := skills/decision-spec-plan
CODE := $(SKILL)/scripts $(SKILL)/tests
# coverage's SQLite data stays off Windows mounts, where it fails with disk I/O errors; one
# directory per checkout, so a parallel worktree's `coverage erase` cannot wipe this one's data
export COVERAGE_FILE ?= $(or $(TMPDIR),/tmp)/dsp-coverage$(subst /,-,$(CURDIR))/.coverage
# branch coverage measured 93.74% on 3c70cb6, 94.40% on b1678a6 (2026-11-11); only ever raised
COV_MIN := 94

.PHONY: check static fmt lint types arch deps dead workflows test cov

check: static cov

static: fmt lint types arch deps dead workflows

fmt:
	ruff format --check $(CODE)

lint:
	ruff check $(CODE)

types:
	basedpyright

arch:
	PYTHONPATH=$(SKILL)/scripts lint-imports

# the shipped scripts stay stdlib-only; tests are dev code, so their packages are dev pins
deps:
	deptry $(SKILL)/scripts

dead:
	vulture $(CODE) --min-confidence 80

workflows:
	actionlint
	zizmor --persona=pedantic .github/workflows

test:
	python3 -m pytest

cov:
	mkdir -p $(dir $(COVERAGE_FILE))
	coverage erase
	coverage run -m pytest
	coverage combine -q
	coverage report --fail-under=$(COV_MIN)

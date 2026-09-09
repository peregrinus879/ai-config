# Maintenance automation for EyrAgents. Run from the repo root on any machine.
# The package list here is the single source of truth for the stow command sets.
# Stow runs without directory folding so every managed parent under $HOME stays
# a real directory and only leaf files are links.

SHELL := /bin/bash
PACKAGES := agents claude-code codex opencode hermes
STOW := stow --no-folding --ignore='__pycache__' -t ~
TOOL_PACKAGES := claude-code codex opencode hermes
# Each skill under ~/.agents/skills deploys as one directory link, which Codex's
# loader follows where it skips file links; Stow leaves that directory to
# scripts/prepare-stow.sh --link-skills.
AGENTS_STOW := $(STOW) --ignore='\.agents/skills'
SHELLCHECK_FILES := claude-code/.claude/statusline.sh \
  templates/hooks/commit-gate \
  $(filter-out %/spar-payload-scan %.py,$(wildcard agents/.agents/skills/*/scripts/*)) \
  $(wildcard scripts/*.sh tests/*.sh)

.PHONY: help stow unstow dry-run restow require-clone check-skills install-gate migrate-codex-config migrate-hermes-config lint test check verify-deploy verify canary clean

# Deployment goals and their guards must never race, including `make -j clean restow`.
.NOTPARALLEL:

help:
	@echo "Targets:"
	@echo "  stow           Clean dangling links, stow packages, link skills, install the gate, reconcile Codex and Hermes configs"
	@echo "  unstow         Remove all package links and the skill directory links"
	@echo "  dry-run        Preview Stow actions"
	@echo "  restow         Guard, preflight skills, clean, refresh links, install the gate, reconcile Codex and Hermes configs"
	@echo "  check-skills   Read-only preflight of every managed skill directory"
	@echo "  install-gate   Install templates/hooks/commit-gate as a real file under ~/.agents/hooks"
	@echo "  migrate-codex-config  Reconcile ~/.codex/config.toml with the template, keeping host tables"
	@echo "  migrate-hermes-config Reconcile private ~/.hermes/config.yaml and compose shared guidance"
	@echo "  lint           ShellCheck, Python, and plugin syntax checks over managed scripts"
	@echo "  test           Fast tests: configuration boundaries, bridges, statusline, preparation, commit gate"
	@echo "  check          Repository checks: links, JSON/TOML, Hermes YAML/policy and fixture tests (runs in CI)"
	@echo "  verify-deploy  Check every package file resolves to its deployed target"
	@echo "  verify         lint, check, and verify-deploy"
	@echo "  canary         Up to six live calls per tool; interactive-only OpenCode checks reported separately (not a gate)"
	@echo "  clean          Remove dangling links that point into this repository's packages"

stow: clean
	$(STOW) -v $(TOOL_PACKAGES)
	$(AGENTS_STOW) -v agents
	bash scripts/prepare-stow.sh --link-skills
	$(MAKE) --no-print-directory install-gate
	bash scripts/prepare-stow.sh --migrate-codex-config
	bash scripts/prepare-stow.sh --migrate-hermes-config

unstow: require-clone check-skills
	$(STOW) -D -v $(TOOL_PACKAGES)
	$(AGENTS_STOW) -D -v agents
	bash scripts/prepare-stow.sh --unlink-skills

dry-run:
	$(STOW) -n -v $(TOOL_PACKAGES)
	$(AGENTS_STOW) -n -v agents

restow: clean
	$(STOW) -R -v $(TOOL_PACKAGES)
	$(AGENTS_STOW) -R -v agents
	bash scripts/prepare-stow.sh --link-skills
	$(MAKE) --no-print-directory install-gate
	bash scripts/prepare-stow.sh --migrate-codex-config
	bash scripts/prepare-stow.sh --migrate-hermes-config

# The hook runs outside the Codex sandbox, so its executable lives outside
# every workspace as a real file the sandboxed agent cannot write.
GATE := $(HOME)/.agents/hooks/commit-gate
# Preserve an override as data, never recursively expand Make expressions.
override export GATE := $(value GATE)
install-gate: require-clone
	@bash scripts/prepare-stow.sh --install-gate

# A managed endpoint that is a link must resolve into this clone; a reference
# clone of the same repository must never redeploy the packages from itself.
require-clone:
	@bash scripts/prepare-stow.sh --require-clone

check-skills: require-clone
	@bash scripts/prepare-stow.sh --check-skills

migrate-codex-config: require-clone
	bash scripts/prepare-stow.sh --migrate-codex-config

migrate-hermes-config: require-clone
	bash scripts/prepare-stow.sh --migrate-hermes-config

lint:
	shellcheck -s bash $(SHELLCHECK_FILES)
	python3 -I -c 'import sys; [compile(open(p, "rb").read(), p, "exec") for p in sys.argv[1:]]' \
	  agents/.agents/skills/spar/scripts/spar-payload-scan scripts/reconcile-codex-config.py scripts/reconcile-hermes-config.py \
	  hermes/.hermes/plugins/eyragents/__init__.py tests/hermes.py tests/hermes-runtime.py tests/hermes-live.py tests/hermes-live-fixtures.py tests/config-contracts.py \
	  agents/.agents/skills/commit/scripts/governance.py tests/commit-governance.py
	@set -e; for plugin in opencode/.config/opencode/plugins/*.js; do node --check "$$plugin"; done
	@echo "ok:   lint"

test:
	python3 tests/config-contracts.py
	python3 tests/hermes.py
	python3 tests/hermes-live-fixtures.py
	bash tests/statusline.sh
	bash tests/prepare-stow.sh
	bash tests/reconcile-codex.sh
	bash tests/review-brief.sh
	bash tests/spar-bridges.sh
	bash tests/commit-gate.sh
	bash tests/opencode-auditor.sh
	bash tests/opencode-scratch.sh
	bash tests/canary.sh
	bash tests/publish-clip.sh
	@echo "ok:   test"

check:
	@fail=0; \
	while IFS= read -r -d '' link; do \
	  echo "FAIL: package symlink does not resolve: $$link"; fail=1; \
	done < <(find $(PACKAGES) .agents .claude -type l -xtype l -print0); \
	[[ $$fail -eq 0 ]] && echo "ok:   package and project symlinks resolve"; \
	while IFS= read -r -d '' f; do \
	  case $$f in \
	    *.toml) python3 -c 'import sys, tomllib; tomllib.load(open(sys.argv[1], "rb"))' "$$f" ;; \
	    *) python3 -c 'import sys, json; json.load(open(sys.argv[1], encoding="utf-8"))' "$$f" ;; \
	  esac && echo "ok:   $$f parses" || { echo "FAIL: $$f does not parse"; fail=1; }; \
	done < <(git ls-files -z -- '*.json' '*.toml'); \
	exit $$fail
	@$(MAKE) --no-print-directory test
	@echo "ok:   check"

# Every non-ignored package file must resolve to the same inode as its
# deployed target, every package directory must be a real directory in $HOME,
# and a retired source must leave no link behind. GNU Stow ignores .gitignore
# files, so they are skipped.
verify-deploy:
	@bash scripts/prepare-stow.sh --check-gate
	@python3 scripts/reconcile-hermes-config.py check "$(CURDIR)"
	@fail=0; \
	while IFS= read -r -d '' src; do \
	  [[ "$$src" == */.gitignore ]] && continue; \
	  target="$$HOME/$${src#*/}"; \
	  if [[ ! -e $$src && ! -L $$src ]]; then \
	    if git diff --quiet -- "$$src"; then \
	      echo "FAIL: tracked package source is missing without a pending deletion: $$src"; fail=1; \
	    elif [[ -L $$target ]]; then \
	      echo "FAIL: retired package endpoint remains linked: $$target"; fail=1; \
	    elif [[ ! -e $$target ]]; then \
	      echo "ok:   retired package endpoint absent: $$target"; \
	    elif [[ -f $$target && -O $$target ]]; then \
	      echo "ok:   retired package endpoint is owner-controlled: $$target"; \
	    else \
	      echo "FAIL: retired package endpoint has an unsupported replacement: $$target"; fail=1; \
	    fi; \
	    continue; \
	  fi; \
	  if [[ $$(readlink -f -- "$$target") == "$$(readlink -f -- "$$src")" ]]; then \
	    echo "ok:   $$target resolves into the repo"; \
	  else \
	    echo "FAIL: $$target does not resolve into the repo"; fail=1; \
	  fi; \
	done < <(git ls-files -z --cached --others --exclude-standard -- $(PACKAGES)); \
	while IFS= read -r dir; do \
	  target="$$HOME/$${dir#*/}"; \
	  case $$dir in \
	    agents/.agents/skills/*/*) continue ;; \
	    agents/.agents/skills/*) \
	      if [[ -L $$target && $$(readlink -f -- "$$target") == "$(CURDIR)/$$dir" ]]; then echo "ok:   skill directory link resolves into the repo: $$target"; \
	      else echo "FAIL: skill directory is not one link into the repo (run make restow): $$target"; fail=1; fi ;; \
	    *) if [[ -d $$target && ! -L $$target ]]; then :; \
	       else echo "FAIL: managed directory is folded or missing: $$target"; fail=1; fi ;; \
	  esac; \
	done < <(git ls-files --cached --others --exclude-standard -- $(PACKAGES) | \
	  while IFS= read -r src; do [[ -e $$src || -L $$src ]] || continue; dir=$${src%/*}; \
	  while [[ $$dir == */* ]]; do echo "$$dir"; dir=$${dir%/*}; done; done | sort -u); \
	for path in package.json package-lock.json bun.lock bun.lockb node_modules; do \
	  target="opencode/.config/opencode/$$path"; \
	  if [[ ! -e $$target && ! -L $$target ]]; then :; \
	  else echo "FAIL: generated OpenCode state reached the package source: $$target"; fail=1; fi; \
	done; \
	for b in review-brief spar-claude spar-codex spar-payload-scan commit-candidate commit-apply publish-bind publish-verify publish-clip; do \
	  skill=spar; [[ $$b == commit-* ]] && skill=commit; [[ $$b == publish-* ]] && skill=publish; \
	  if [[ -x "$$HOME/.agents/skills/$$skill/scripts/$$b" ]]; then echo "ok:   $$b executable"; else echo "FAIL: $$b missing or not executable"; fail=1; fi; \
	done; \
	config="$$HOME/.codex/config.toml"; \
	if [[ -f $$config && ! -L $$config && -O $$config && $$(stat -c '%a' -- "$$config") =~ ^[46]00$$ ]] && \
	  python3 scripts/reconcile-codex-config.py check templates/codex/config.toml "$$config" && \
	  HOST_CODEX_CONFIG="$$config" python3 tests/config-contracts.py >/dev/null; then \
	  echo "ok:   host Codex config carries the template boundaries"; \
	else echo "FAIL: host Codex config is missing, exposed, or drifted from the template (run make restow)"; fail=1; fi; \
	if [[ -e "$$HOME/.config/opencode/opencode.jsonc" ]]; then \
	  echo "FAIL: stray ~/.config/opencode/opencode.jsonc shadows the stowed config"; fail=1; \
	else echo "ok:   no stray opencode.jsonc"; fi; \
	exit $$fail

verify: lint check verify-deploy
	@echo "ok:   verify"

# Live behavior of the deployed tools: up to six model calls per tool from a
# throwaway repository. Run after make restow.
canary:
	bash scripts/canary.sh

clean: check-skills
	bash scripts/prepare-stow.sh

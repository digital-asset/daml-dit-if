version := $(shell python3 -c "import configparser; config = configparser.ConfigParser(); config.read('pyproject.toml'); print(config['tool.poetry']['version'][1:-1])")

daml_dit_if_files := $(shell find daml_dit_if -name '*.py') README.md
daml_dit_if_bdist := dist/daml_dit_if-$(version)-py3-none-any.whl
daml_dit_if_sdist := dist/daml_dit_if-$(version).tar.gz

build_dir := build/.dir
poetry_build_marker := build/.poetry.build
poetry_install_marker := build/.poetry.install

SRC_FILES=$(shell find daml_dit_if -type f)

####################################################################################################
## GENERAL TARGETS                                                                                ##
####################################################################################################

.PHONY: all
all: build

.PHONY: clean
clean:
	find . -name *.pyc -print0 | xargs -0 rm
	find . -name __pycache__ -print0 | xargs -0 rm -fr
	rm -fr build dist $(LIBRARY_NAME).egg-info test-reports

.PHONY: deps
deps: $(poetry_install_marker)

.PHONY: format
format:
	poetry run isort daml_dit_if
	poetry run black daml_dit_if

.PHONY: publish
publish: build
	poetry publish

.PHONY: install
install: build
	pip3 install --force $(daml_dit_if_bdist)

.PHONY: build
build: test $(daml_dit_if_bdist) $(daml_dit_if_sdist)

.PHONY: version
version:
	@echo $(version)


####################################################################################################
## TEST TARGETS                                                                                   ##
####################################################################################################

.PHONY: format-test
format-test:
	poetry run isort daml_dit_if --check-only
	poetry run black daml_dit_if . --check --extend-exclude='^/target'

.PHONY: typecheck
typecheck:
	poetry run python3 -m mypy --config-file pytest.ini  -p daml_dit_if

.PHONY: test
test: format-test typecheck


####################################################################################################
## file targets                                                                                   ##
####################################################################################################

$(build_dir):
	@mkdir -p build
	@touch $@

$(poetry_build_marker): $(build_dir) pyproject.toml $(SRC_FILES)
	poetry build
	touch $@

$(poetry_install_marker): $(build_dir) poetry.lock
	touch $@

$(daml_dit_if_bdist): $(poetry_build_marker)

$(daml_dit_if_sdist): $(poetry_build_marker)

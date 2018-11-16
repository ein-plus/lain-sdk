PACKAGE_NAME = einplus_lain_sdk
VERSION = $(shell cat lain_sdk/__init__.py | ag -o "(?<=').+(?=')")

test: clean
	py.test -s -x -vvvv --doctest-modules --junit-xml=unittest.xml tests lain_sdk/yaml/parser.py lain_sdk/util.py

test-cov: clean
	py.test -vvvv -s -x --doctest-modules --cov-report html --cov-report=term --cov=lain_sdk tests lain_sdk/yaml/parser.py lain_sdk/util.py

clean:
	- find . -iname "*__pycache__" | xargs rm -rf
	- find . -iname "*.pyc" | xargs rm -rf
	- rm -rf dist build lain_sdk.egg-info .coverage htmlcov unittest.xml

overwrite-package:
	devpi login root --password=$(PYPI_ROOT_PASSWORD)
	devpi remove $(PACKAGE_NAME)==$(VERSION) || true
	devpi upload

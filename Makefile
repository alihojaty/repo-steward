.PHONY: test package verify clean

test:
	python3 -m unittest discover -s repo-steward/tests -p 'test_*.py' -v

package: test
	mkdir -p dist
	rm -f dist/repo-steward.zip
	COPYFILE_DISABLE=1 zip -r -X dist/repo-steward.zip repo-steward \
		-x '*/__pycache__*' '*.pyc' '*.DS_Store' '*/._*' 'repo-steward/README*.md'

verify:
	unzip -l dist/repo-steward.zip

clean:
	rm -rf dist
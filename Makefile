test:
	@echo no tests yet, lol

clean:
	rm -rf htmlcov
	find . -iname __pycache__ -o -iname '*.pyc' | xargs rm -rf
	rm -f .coverage
	rm -rf preserves.egg-info build dist

# sudo apt install python3-wheel twine
publish: clean
	python3 setup.py sdist bdist_wheel
	twine upload dist/*

veryclean: clean
	rm -rf pyenv

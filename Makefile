install:
	pip install -r requirements.txt

download:
	python scripts/download_dataset.py

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	LLM_MODE=stub pytest tests/ -v

test-unit:
	LLM_MODE=stub pytest tests/unit/ -v

test-integration:
	LLM_MODE=stub pytest tests/integration/ -v

eval:
	python scripts/evaluate.py

.PHONY: install download run test test-unit test-integration eval

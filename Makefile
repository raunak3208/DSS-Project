.PHONY: up down logs test reset scenario-% dashboard-dev
up:        ; test -f .env || cp .env.example .env; docker compose up --build -d
down:      ; docker compose down -v
logs:      ; docker compose logs -f processor controller
reset:     ; curl -s -X POST localhost:8080/api/chaos/reset
test:      ; python -m pytest tests -q
scenario-%: ; python scripts/run_scenario.py scenarios/$*.json --auto-approve
dashboard-dev: ; cd dashboard && npm install && npm run dev

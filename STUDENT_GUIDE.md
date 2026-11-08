# Lab 9: build and deploy your application

## Find your team and choose a component

1. **Open the registration page:** [Lab 9 website](https://maai-se-lab9.inemo.chatgpt.site).
2. **Register:** enter your full name exactly as shown in the LMS and your GitHub username. Click **Register / save my name**.
3. **Find your team:** keep the page open until the instructor publishes teams. Your team number, application, and teammates will appear automatically. If you return later, enter your GitHub username and click **Already registered? Find my team**.
4. **Meet your teammates:** find the people listed on your team page. Sit together or open a shared call. Confirm that everyone sees the same team and application.
5. **Get the starter:** click **Download starter ZIP** and extract it. You can do this before anyone chooses a component.
6. **Read the assignment:** open `PROJECT.md` to understand the application and `TASKS.md` to read the requirements for each component.
7. **Choose your component:** agree with your teammates who will build each component listed below. On the website, each student clicks **Choose this component** for their own assignment. Check that your name appears beside it.
8. **Review each other's work:** when your pull request is ready, ask any teammate to review it before merging. Your team decides who reviews each pull request. You cannot review your own work.

**Arriving late?** Follow steps 1–2 as usual. If teams are already published, you will automatically join the smallest team with space. Then continue from step 4. Existing members keep their teams and selected components.


| Owner | Complete component |
| --- | --- |
| W | Website and public API (`web`). |
| I | Application-specific domain service, named in `TASKS.md`. |
| A | Model training, evaluation, and CPU inference API (`ai`). |
| D | **PostgreSQL DATABASE and database-access service (`data`)**, including tables, relationships, constraints, indexes, schema initialization/migrations, and persistent storage. |

In a three-person team, W owns both the website and domain service, including I's checkpoints. Both remain separate services. If a fourth member joins, W keeps the website and hands over the domain service when that member selects I. Confirm component ownership again after arrivals or choice changes.

## Get the starter and create your team repository

1. On your assigned team's page, click **Download starter ZIP**. It contains the starter, data, and task documents for your application. You can download it immediately, before everyone chooses a component.
2. One teammate extracts the ZIP, creates an empty GitHub repository, and pushes the extracted folder's contents. Include the hidden `.github`, `.gitignore`, `.dockerignore`, and `.env.example` files.
3. That teammate invites the others as collaborators, gives the examiner access, and sends the repository URL to the instructor to add to the team page.
4. Everyone else clones that same repository. Open `STUDENT_GUIDE.md`, `PROJECT.md`, and `TASKS.md` and follow the startup steps below.

The ZIP contains shared project files, not team membership or component choices. Use the live team page for current component owners. If you already have a team repository, continue there rather than replacing your work with a fresh starter download.

## Requirements for each component

Implement the application-specific features in `PROJECT.md` and `TASKS.md`, together with the requirements below.

### Every component owner

- Implement, test, document, containerize, and deploy your complete component.
- Supply an HTTP API, health endpoint, Dockerfile, configuration, and run instructions.
- Agree request, response, and error formats with teammates before coding.
- Test successful requests, invalid inputs, relevant duplicates/conflicts, and dependency errors. Use fixtures or mocked HTTP where appropriate.
- Record API examples, test commands/results, and deployment checks in your component's evidence file.

### W — Website and public API (`web`)

- Implement the browser workflow specified for your application and connect it to the other services through HTTP.
- Validate user inputs and render submitted content as text.
- Show clear empty, loading, success, and error states.
- Deploy a public HTTPS website that an examiner can use without a terminal.

### I — Domain microservice

- Implement your application's domain workflow, such as importing news, as specified in `TASKS.md`.
- Run it as a separate service with its own HTTP API.
- Call the ML and data services as required by the workflow; do not access PostgreSQL directly.
- If needed, normalize or truncate text sent to the model while preserving the full text in storage.

### A — Machine-learning service (`ai`)

**Training is mandatory. A simple CPU classifier is sufficient.**

- Prepare or extend labeled training data and write or adapt a reproducible training script.
- Train the classifier and save a versioned model artifact.
- Evaluate on held-out data covering every category, including at least three new examples excluded from training. Record expected/actual labels, accuracy, and a limitation.
- Load your trained artifact when `ai` starts and return its version with predictions.
- Reject empty inference text and enforce the 1000-character input limit.
- Record the training command, code changes, data split, artifact/version, and evaluation results in `evidence/ai.md`. Replace the baseline `MODEL_CARD.md` with your model's details.

The unchanged starter, restarting its built-in training, or merely loading a pretrained model does not complete the ML assignment.

### D — PostgreSQL DATABASE and database-access service (`data`)

- Implement the tables, relationships, constraints, indexes, and initialization/migrations required by your application.
- Deploy PostgreSQL with persistent storage and a separate `data` service exposing the database operations through HTTP.
- Make `data` the only application service that accesses PostgreSQL directly.
- Verify that saved records remain available after a page refresh and an application restart.

## Shared architecture and delivery

- Run **four independent application services plus PostgreSQL**. Services communicate through HTTP; one host can run all five containers. Only `web` needs public HTTPS access.
- Check real service-to-service requests after deployment and verify the complete application workflow together.
- Keep secrets in the host environment or an ignored `.env`, never in source or evidence.
- Keep the entire application in **one GitHub repository**: all services, database schema/migrations, model training/evaluation code and data or reproducible data-preparation instructions, model-loading instructions, sample inputs, tests, Dockerfiles, deployment configuration, and documentation.
- All owners contribute through reviewed pull requests. Give the examiner repository access.

## Start from the supplied foundation

Prepare GitHub, Docker/Compose, hosting, and HTTPS access before the 120-minute session. Use synthetic classroom data. Implement the bounded workflow in `PROJECT.md`; extra features are unnecessary.

The starter implements three services for single-text classification/storage. Add the domain service identified in `DEPLOYMENT.md` and extend the existing services for your product. Keep the baseline `/api/tickets`, `/tickets`, and `/predict` contracts working.

1. Run `python3 -m unittest discover -s tests -v`.
2. Copy `.env.example` to `.env` and configure the database password and project name.
3. Run `docker compose up -d --build --wait` and inspect `docker compose ps`.

These commands initially start only the three baseline services and PostgreSQL. Add the fourth service to Compose. The baseline tests and `tools/smoke.py` check only the foundation; add tests for your product.

### Shared code you can extend

- `Handler.read_body()` accepts raw XML/CSV uploads up to 1 MiB; `body()` parses JSON with the same configurable limit. Send a file as the request body, not multipart form data. Forward it with `request_json(url, raw_body=content, content_type="text/csv")` (or `"application/xml"`). The model's separate 1000-character limit still applies.
- Routes receive the path without its query string. Read filters with `self.query_param("q")` or `self.query_param("category")`; `/api/tickets?q=wifi&category=it` shows the pattern (use your variant's labels). `request_json()` preserves client errors such as 404/409 and supports `method="PATCH"` or `"DELETE"`.
- The data service applies `services/data/migrations/*.sql` at startup. Add numbered files such as `003_project_tables.sql`; do not edit applied files. Migrations run transactionally, are recorded once, and preserve existing data. To run them explicitly: `docker compose run --rm data python -m services.data.migrate`.

## Hosting option: Render

You may use [Render](https://render.com/docs/web-services). Connect your team's GitHub repository, deploy each of the four application services separately using its [Dockerfile](https://render.com/docs/docker), and create a Render Postgres database. Configure service URLs and secrets in Render. Web services must listen on `0.0.0.0` and the configured `PORT`; Render provides a public HTTPS URL for the website.

Check the [free-tier limits](https://render.com/docs/free) when choosing instances:

- Free web services sleep after 15 minutes without incoming traffic and take about a minute to restart. Their 750 monthly instance hours are shared across the workspace's services.
- Free Postgres databases expire 30 days after creation. Ensure yours remains available throughout the checking window, or upgrade it.
- Free web services cannot receive private-network traffic. Use paid private services for internal APIs, or public web-service URLs with service-to-service authentication.

Test the full workflow after an idle period and check your remaining quota before examination. Render is optional; another host is acceptable if it meets the same deployment requirements.

## Review checkpoints

W1/W2, I1/I2, A1/A2, and D1/D2 are two reviewed PR checkpoints within each owner's complete assignment: first implementation, then integration, tests, and release configuration. Keep ownership of the same component throughout. Your team chooses who reviews each pull request. Ask a teammate other than the author to inspect the diff, run or witness relevant checks, and state what they verified before approving. Obtain that review before merging; the website does not assign reviewers.

## Individual lab bonus

**Each student must personally complete at least one assigned task to qualify for the lab bonus.** Completing the application as a team does not automatically qualify every team member. Identify your completed task and link your own pull requests and component evidence in `SUBMISSION.md` so the examiner can verify your contribution.

## Finish and submit

After merging reviewed changes, run the service tests and deploy the final commit. From outside the classroom network, complete the examiner's workflow in `PROJECT.md` using fresh input. Confirm all four services and PostgreSQL participate and the saved results persist.

The lab is done only when **all requested components and features are present and an examiner can open the public website and use the application** without a terminal. Complete `SUBMISSION.md` with release details and evidence. Record the full deployed commit SHA after the final merge. Keep the application and repository accessible throughout the announced checking window.

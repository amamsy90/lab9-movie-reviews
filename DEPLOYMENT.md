# Movie review board: deployment map

Follow the setup and release procedure in [STUDENT_GUIDE.md](STUDENT_GUIDE.md).

| Service | Connections and configuration |
| --- | --- |
| `web` | Public HTTPS; calls `reviews` for processing/actions and `data` for saved views. |
| `reviews` | Add `services/reviews/`, its Dockerfile, and its entry in `compose.yaml`. Configure internal `ai` and `data` URLs. |
| `ai` | Loads your trained CPU model artifact; accepts documents from `reviews`. |
| `data` | Receives database credentials; provides storage/query APIs. |
| PostgreSQL | Persistent volume and schema for reviews. |

Record actual environment variable names and commands in the component evidence files linked from [TASKS.md](TASKS.md).

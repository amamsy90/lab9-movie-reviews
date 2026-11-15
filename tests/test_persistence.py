"""Opt-in Docker persistence check; never uses Compose or existing databases.

Run from the repository root with Docker available:
docker build -t lab9-movie-reviews-team-data -f services/data/Dockerfile .
TEST_PERSISTENCE=1 python3 -B -m unittest discover -s tests -p test_persistence.py -v

Creates labelled containers and a new volume, verifies isolation before startup,
and removes only those owned resources afterward. AI is an HTTP test double;
Data, Reviews, and Web run their unchanged entrypoints in separate containers.
"""
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from uuid import uuid4


@unittest.skipUnless(os.environ.get("TEST_PERSISTENCE") == "1", "requires opt-in disposable Docker stack")
class PersistenceTests(unittest.TestCase):
    def docker(self, *arguments):
        result = subprocess.run(
            ["docker", *arguments], capture_output=True, text=True, timeout=120,
        )
        if result.returncode:
            self.fail(f"docker {' '.join(arguments)} failed: {result.stderr}")
        return result.stdout.strip()

    def inspect(self, name):
        return json.loads(self.docker("inspect", name))[0]

    def setUp(self):
        self.owner = "lab9-d2-persist-" + uuid4().hex[:12]
        self.label = "lab9.d2.persistence.owner"
        self.volume = self.owner + "-storage"
        self.containers = []
        self.volume_created = False
        self.addCleanup(self.cleanup)
        # Refuse to adopt any existing volume, even if a name unexpectedly collides.
        existing = self.docker("volume", "ls", "--format", "{{.Name}}").splitlines()
        self.assertNotIn(self.volume, existing)
        self.docker("volume", "create", "--label", f"{self.label}={self.owner}", self.volume)
        self.volume_created = True
        self.pg = self.owner + "-pg"
        self.docker(
            "create", "--name", self.pg, "--label", f"{self.label}={self.owner}",
            "--network", "none", "--mount", f"type=volume,src={self.volume},dst=/var/lib/postgresql/data",
            "-e", "POSTGRES_DB=d2_persistence", "-e", "POSTGRES_USER=d2_test",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17",
        )
        self.containers.append(self.pg)
        image = "lab9-movie-reviews-team-data:latest"
        root = str(Path(__file__).resolve().parents[1])
        self.apps = {}
        commands = {
            "ai": ["-c", "import sys; sys.path.insert(0, '/app/tests'); "
                   "from test_reviews import FakeAI; from common import serve; serve(FakeAI)"],
            "data": ["-m", "services.data.app"],
            "reviews": ["-m", "services.reviews.app"],
            "web": ["-m", "services.web.app"],
        }
        for service, port in (("ai", 8004), ("data", 8001), ("reviews", 8002), ("web", 8003)):
            name = self.owner + "-" + service
            self.docker(
                "create", "--name", name, "--label", f"{self.label}={self.owner}",
                "--network", f"container:{self.pg}", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=64m",
                "--mount", f"type=bind,src={root},dst=/app,readonly", "--workdir", "/app",
                "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", f"PORT={port}",
                "-e", "DB_HOST=127.0.0.1", "-e", "DB_PORT=5432", "-e", "DB_NAME=d2_persistence",
                "-e", "DB_USER=d2_test", "-e", "DB_PASSWORD=disposable-test-only",
                "-e", "AI_URL=http://127.0.0.1:8004", "-e", "DATA_URL=http://127.0.0.1:8001",
                "-e", "REVIEWS_URL=http://127.0.0.1:8002",
                "--entrypoint", "python", image, "-B", *commands[service],
            )
            self.containers.append(name)
            self.apps[service] = name
        self.verify_isolation(root)  # Must happen before initdb, migrations, or imports.
        self.docker("start", self.pg)
        self.wait_for_postgres()
        self.start_apps()

    def verify_isolation(self, root):
        volume = json.loads(self.docker("volume", "inspect", self.volume))[0]
        self.assertEqual(volume["Labels"][self.label], self.owner)
        pg = self.inspect(self.pg)
        self.assertEqual(pg["HostConfig"]["NetworkMode"], "none")
        self.assertEqual(len(pg["Mounts"]), 1)
        self.assertEqual(pg["Mounts"][0]["Type"], "volume")
        self.assertEqual(pg["Mounts"][0]["Name"], self.volume)
        for name in self.containers:
            info = self.inspect(name)
            self.assertEqual(info["Config"]["Labels"][self.label], self.owner)
            self.assertFalse(info["HostConfig"]["PortBindings"])
            if name != self.pg:
                self.assertIn(info["HostConfig"]["NetworkMode"],
                              (f"container:{self.pg}", f"container:{pg['Id']}"))
                self.assertTrue(info["HostConfig"]["ReadonlyRootfs"])
                for mount in info["Mounts"]:
                    if mount["Type"] == "bind":
                        self.assertEqual(mount["Source"], root)
                        self.assertEqual(mount["Destination"], "/app")
                        self.assertFalse(mount["RW"])
                    else:
                        self.assertEqual(mount["Type"], "tmpfs")

    def wait_for_postgres(self):
        for _ in range(100):
            result = subprocess.run(
                ["docker", "exec", self.pg, "pg_isready", "-U", "d2_test", "-d", "d2_persistence"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                return
            time.sleep(0.1)
        self.fail("Disposable PostgreSQL did not become ready")

    def start_apps(self):
        self.docker("start", *self.apps.values())
        for port in (8001, 8002, 8003):
            script = (
                "import time; from urllib.request import urlopen\n"
                "for attempt in range(100):\n"
                " try:\n"
                f"  response=urlopen('http://127.0.0.1:{port}/healthz', timeout=1); response.close(); break\n"
                " except OSError: time.sleep(0.1)\n"
                "else: raise RuntimeError('Test service did not become healthy')\n"
            )
            self.docker("exec", self.apps["web"], "python", "-B", "-c", script)

    def http(self, port, path, raw=None):
        script = (
            "import json,sys; from urllib.request import Request,urlopen\n"
            "from urllib.error import HTTPError\n"
            "try: response=urlopen(Request(sys.argv[1], data=None if len(sys.argv)==2 "
            "else sys.argv[2].encode(), headers={'Content-Type':'text/csv'}), timeout=15)\n"
            "except HTTPError as error: response=error\n"
            "with response: print(json.dumps([response.status,json.load(response)]))\n"
        )
        args = [] if raw is None else [raw]
        return json.loads(self.docker(
            "exec", self.apps["web"], "python", "-B", "-c", script,
            f"http://127.0.0.1:{port}{path}", *args,
        ))

    def snapshot(self):
        snapshot = {}
        for name, port, path in (
            ("reviews", 8001, "/reviews"), ("movies", 8001, "/movies"),
            ("moon_counts", 8002, "/counts?movie_title=Moon%20Garden"),
            ("silver_counts", 8002, "/counts?movie_title=Silver%20Harbor"),
            ("web_reviews", 8003, "/api/reviews"), ("web_movies", 8003, "/api/movies"),
            ("web_counts", 8003, "/api/counts?movie_title=Moon%20Garden"),
        ):
            status, value = self.http(port, path)
            self.assertEqual(status, 200)
            snapshot[name] = value
        return snapshot

    def test_reviews_survive_container_restarts_and_identical_reimport(self):
        raw = ("review_id,movie_title,review_text\n"
               "persist-1,  Moon   Garden ,Wonderful acting\n"
               "persist-2,Moon Garden,A film about a coastal town\n"
               "persist-3,Moon Garden,Awful dialogue\n"
               "persist-4,Silver Harbor,Wonderful scenery\n")
        status, imported = self.http(8002, "/imports", raw)
        self.assertEqual(status, 200)
        self.assertEqual((imported["added"], imported["duplicates"], imported["skipped"]), (4, 0, 0))
        before = self.snapshot()
        self.assertEqual(before["movies"], ["Moon Garden", "Silver Harbor"])
        by_id = {row["external_id"]: row for row in before["reviews"]}
        self.assertEqual(set(by_id), {f"persist-{index}" for index in range(1, 5)})
        for index, label in enumerate(("positive", "neutral", "negative", "positive"), 1):
            self.assertEqual(by_id[f"persist-{index}"]["sentiment"], label)
            self.assertEqual(by_id[f"persist-{index}"]["model_version"], "test-v1")
        self.assertEqual(before["moon_counts"], {"movie_title": "Moon Garden", "positive": 1,
                                                "neutral": 1, "negative": 1, "total": 3})
        self.assertEqual(before["silver_counts"], {"movie_title": "Silver Harbor", "positive": 1,
                                                  "neutral": 0, "negative": 0, "total": 1})
        self.assertEqual(before["web_reviews"], before["reviews"])
        self.assertEqual(before["web_counts"], before["moon_counts"])
        started = {name: self.inspect(name)["State"]["StartedAt"] for name in self.containers}
        # Stop every application before replacing PostgreSQL's network namespace.
        self.docker("stop", *reversed(list(self.apps.values())))
        self.docker("restart", self.pg)
        self.wait_for_postgres()
        self.start_apps()  # Data's real startup also rechecks applied migrations.
        for name in self.containers:
            self.assertNotEqual(self.inspect(name)["State"]["StartedAt"], started[name])
        self.assertEqual(self.inspect(self.pg)["Mounts"][0]["Name"], self.volume)
        self.assertEqual(self.snapshot(), before)  # Includes internal IDs and timestamps.
        for port, path in ((8002, "/imports"), (8003, "/api/imports")):
            status, repeated = self.http(port, path, raw)
            self.assertEqual(status, 200)
            self.assertEqual((repeated["added"], repeated["duplicates"], repeated["skipped"]), (0, 4, 0))
            self.assertEqual(self.snapshot(), before)
        self.__class__.verified_snapshot = before

    def cleanup(self):
        # Never stop/remove anything unless its unique ownership label matches.
        for name in reversed(self.containers):
            info = self.inspect(name)
            self.assertEqual(info["Config"]["Labels"].get(self.label), self.owner)
            if info["State"]["Running"]:
                self.docker("stop", name)
            self.docker("rm", name)
        if self.volume_created:
            volume = json.loads(self.docker("volume", "inspect", self.volume))[0]
            self.assertEqual(volume["Labels"].get(self.label), self.owner)
            self.assertFalse(self.docker("ps", "-aq", "--filter", f"volume={self.volume}"))
            self.docker("volume", "rm", self.volume)

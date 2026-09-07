import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from memehunter.publish import publish_feed


class PublishTests(unittest.TestCase):
    def test_only_feed_is_published_and_concurrent_code_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); remote=root/"remote.git"; checkout=root/"code"; checkout.mkdir()
            def git(*args,cwd=checkout):
                return subprocess.check_output(["git",*args],cwd=cwd,stderr=subprocess.DEVNULL).decode().strip()
            git("init","--bare",str(remote));git("init","-b","main")
            git("config","user.name","test");git("config","user.email","test@example.com")
            (checkout/"code.txt").write_text("v1")
            git("add","code.txt");git("commit","-m","initial");git("push",str(remote),"main")
            feed=root/"feed.json";feed.write_text(json.dumps({"chain":"robinhood","generated_at":100}))
            first=publish_feed(feed,str(remote),root/"publisher.git")
            git("pull","--ff-only",str(remote),"main")
            (checkout/"code.txt").write_text("v2");git("add","code.txt");git("commit","-m","code update");git("push",str(remote),"main")
            (checkout/".env").write_text("PRIVATE=do-not-publish")
            feed.write_text(json.dumps({"chain":"robinhood","generated_at":200}))
            second=publish_feed(feed,str(remote),root/"publisher.git")
            self.assertNotEqual(first,second)
            self.assertEqual(git("show","main:code.txt",cwd=remote),"v2")
            self.assertNotIn(".env",git("ls-tree","-r","--name-only","main",cwd=remote))
            self.assertEqual(json.loads(git("show","main:feed/signals.json",cwd=remote))["generated_at"],200)
            self.assertEqual(publish_feed(feed,str(remote),root/"publisher.git"),second)
            feed.write_text(json.dumps({"chain":"robinhood","generated_at":150}))
            with self.assertRaises(ValueError):publish_feed(feed,str(remote),root/"publisher.git")


if __name__=="__main__":unittest.main()

#!/usr/bin/env python3
"""
Unit tests for mctool.py - testing business logic only (no TUI).
Uses unittest.mock to avoid external calls.
"""

import json
import os
import sys
import tempfile
import shutil
import tarfile
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock, mock_open

# Import from mctool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mctool import Config, MinecraftServer, BackupManager, MANIFEST_URL


class TestConfig(unittest.TestCase):
    """Tests for Config class - JSON config management"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, ".mctool.json")
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_default_config_created(self):
        """Config should have sensible defaults when no file exists"""
        config = Config(self.test_dir)
        
        self.assertEqual(config.get("server_dir"), self.test_dir)
        self.assertEqual(config.get("ram_gb"), 4)
        self.assertIsNone(config.get("current_version"))
        self.assertTrue(config.get("auto_backup"))
        self.assertEqual(config.get("max_backups"), 5)
    
    def test_save_and_load(self):
        """Config should persist to JSON and reload correctly"""
        config = Config(self.test_dir)
        config.set("current_version", "1.21.4")
        config.set("ram_gb", 16)
        
        # Create new instance to test loading
        config2 = Config(self.test_dir)
        
        self.assertEqual(config2.get("current_version"), "1.21.4")
        self.assertEqual(config2.get("ram_gb"), 16)
    
    def test_corrupted_config_fallback(self):
        """Corrupted JSON should fallback to defaults"""
        # Write garbage to config file
        os.makedirs(self.test_dir, exist_ok=True)
        with open(self.config_path, 'w') as f:
            f.write("{invalid json here")
        
        config = Config(self.test_dir)
        
        # Should use defaults
        self.assertEqual(config.get("ram_gb"), 4)
    
    def test_partial_config_merge(self):
        """Missing keys should be filled from defaults"""
        os.makedirs(self.test_dir, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump({"ram_gb": 32}, f)  # Only one key
        
        config = Config(self.test_dir)
        
        self.assertEqual(config.get("ram_gb"), 32)  # From file
        self.assertEqual(config.get("max_backups"), 5)  # From defaults
    
    def test_get_with_default(self):
        """get() should return custom default for missing keys"""
        config = Config(self.test_dir)
        
        self.assertIsNone(config.get("nonexistent"))
        self.assertEqual(config.get("nonexistent", "fallback"), "fallback")


class TestMinecraftServerVersionFetching(unittest.TestCase):
    """Tests for Mojang API version fetching"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = Config(self.test_dir)
        self.server = MinecraftServer(self.config)
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('urllib.request.urlopen')
    def test_fetch_versions_success(self, mock_urlopen):
        """Should parse Mojang manifest correctly"""
        fake_manifest = {
            "versions": [
                {"id": "1.21.4", "type": "release", "url": "https://example.com/1.21.4.json"},
                {"id": "1.21.3", "type": "release", "url": "https://example.com/1.21.3.json"},
                {"id": "24w50a", "type": "snapshot", "url": "https://example.com/24w50a.json"},
            ]
        }
        
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = json.dumps(fake_manifest).encode()
        mock_urlopen.return_value = mock_response
        
        # Patch json.load to work with our mock
        with patch('json.load', return_value=fake_manifest):
            versions = self.server.fetch_versions(limit=10)
        
        self.assertEqual(len(versions), 3)
        self.assertEqual(versions[0]["id"], "1.21.4")
        self.assertEqual(versions[0]["type"], "release")
        self.assertEqual(versions[2]["type"], "snapshot")
    
    @patch('urllib.request.urlopen')
    def test_fetch_versions_network_error(self, mock_urlopen):
        """Should return empty list on network failure"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Network error")
        
        versions = self.server.fetch_versions()
        
        self.assertEqual(versions, [])
    
    @patch('urllib.request.urlopen')
    def test_fetch_versions_limit(self, mock_urlopen):
        """Should respect the limit parameter"""
        fake_manifest = {
            "versions": [{"id": f"1.21.{i}", "type": "release", "url": f"url{i}"} 
                        for i in range(100)]
        }
        
        with patch('json.load', return_value=fake_manifest):
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            versions = self.server.fetch_versions(limit=5)
        
        self.assertEqual(len(versions), 5)
    
    @patch('urllib.request.urlopen')
    def test_get_server_jar_url(self, mock_urlopen):
        """Should extract server.jar URL from version manifest"""
        fake_version_data = {
            "downloads": {
                "server": {
                    "url": "https://piston-data.mojang.com/server.jar",
                    "sha1": "abc123"
                }
            }
        }
        
        with patch('json.load', return_value=fake_version_data):
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            url = self.server.get_server_jar_url("https://example.com/version.json")
        
        self.assertEqual(url, "https://piston-data.mojang.com/server.jar")
    
    @patch('urllib.request.urlopen')
    def test_get_server_jar_url_missing(self, mock_urlopen):
        """Should return None if server download not available"""
        fake_version_data = {"downloads": {"client": {"url": "client.jar"}}}
        
        with patch('json.load', return_value=fake_version_data):
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response
            
            url = self.server.get_server_jar_url("https://example.com/version.json")
        
        self.assertIsNone(url)

class TestMinecraftServerProcessControl(unittest.TestCase):
    """Tests for server start/stop/status"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = Config(self.test_dir)
        self.server = MinecraftServer(self.config)
        self.session_name = self.config.get_session_name()  # Dynamic session name
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('subprocess.run')
    def test_is_running_true(self, mock_run):
        """Should detect running server from screen -ls output"""
        mock_run.return_value = MagicMock(
            stdout=f"There is a screen on:\n\t12345.{self.session_name}\t(Detached)\n"
        )
        
        self.assertTrue(self.server.is_running())
    
    @patch('subprocess.run')
    def test_is_running_false(self, mock_run):
        """Should detect stopped server"""
        mock_run.return_value = MagicMock(stdout="No Sockets found")
        
        self.assertFalse(self.server.is_running())
    
    @patch('subprocess.run')
    def test_is_running_screen_not_found(self, mock_run):
        """Should handle missing screen command"""
        mock_run.side_effect = FileNotFoundError()
        
        self.assertFalse(self.server.is_running())
    
    @patch('subprocess.run')
    def test_start_no_jar(self, mock_run):
        """Should fail if server.jar doesn't exist"""
        success, msg = self.server.start()
        
        self.assertFalse(success)
        self.assertIn("not found", msg.lower())
    
    @patch('subprocess.run')
    def test_start_already_running(self, mock_run):
        """Should fail if server already running"""
        # Create fake jar
        jar_path = os.path.join(self.test_dir, "server.jar")
        open(jar_path, 'w').close()
        
        # Mock is_running to return True (session name in output)
        mock_run.return_value = MagicMock(stdout=f"12345.{self.session_name}")
        
        success, msg = self.server.start()
        
        self.assertFalse(success)
        self.assertIn("already running", msg.lower())
    
    @patch('subprocess.run')
    def test_start_success(self, mock_run):
        """Should start server with correct screen command"""
        # Create fake jar
        jar_path = os.path.join(self.test_dir, "server.jar")
        open(jar_path, 'w').close()
        
        # First call: screen -ls (not running)
        # Second call: java -version (validate java)
        # Third call: screen start
        # Fourth call: screen -ls (running now)
        mock_run.side_effect = [
            MagicMock(stdout="No Sockets found"),  # is_running check
            MagicMock(returncode=0),  # java -version
            MagicMock(returncode=0),  # start command
            MagicMock(stdout=f"12345.{self.session_name}"),  # is_running after start
        ]
        
        success, msg = self.server.start()
        
        self.assertTrue(success)
        
        # Verify screen command was called correctly (3rd call)
        start_call = mock_run.call_args_list[2]
        cmd = start_call[0][0]
        self.assertIn("screen", cmd)
        self.assertIn("-dmS", cmd)
        self.assertIn(self.session_name, cmd)
    
    @patch('subprocess.run')
    def test_stop_not_running(self, mock_run):
        """Should fail if server not running"""
        mock_run.return_value = MagicMock(stdout="No Sockets found")
        
        success, msg = self.server.stop()
        
        self.assertFalse(success)
        self.assertIn("not running", msg.lower())
    
    @patch('subprocess.run')
    def test_send_command_saves_history(self, mock_run):
        """Should save commands to history"""
        # is_running check returns True
        mock_run.return_value = MagicMock(stdout=f"12345.{self.session_name}")
        
        self.server.send_command("say hello")
        
        history = self.config.get("command_history", [])
        self.assertIn("say hello", history)
    
    @patch('subprocess.run')
    def test_send_command_history_limit(self, mock_run):
        """Should limit command history to 20 entries"""
        mock_run.return_value = MagicMock(stdout=f"12345.{self.session_name}")
        
        for i in range(25):
            self.server.send_command(f"cmd{i}")
        
        history = self.config.get("command_history", [])
        self.assertLessEqual(len(history), 20)


class TestBackupManager(unittest.TestCase):
    """Tests for backup creation and management"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = Config(self.test_dir)
        self.config.set("current_version", "1.21.4")
        self.backup = BackupManager(self.config)
        
        # Create fake world folder
        self.world_dir = os.path.join(self.test_dir, "world")
        os.makedirs(self.world_dir)
        
        # Create level.dat to mark as world folder
        with open(os.path.join(self.world_dir, "level.dat"), 'w') as f:
            f.write("fake level data")
        
        # Create some region files
        region_dir = os.path.join(self.world_dir, "region")
        os.makedirs(region_dir)
        with open(os.path.join(region_dir, "r.0.0.mca"), 'w') as f:
            f.write("fake region data")
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_get_world_folders(self):
        """Should find folders with level.dat"""
        worlds = self.backup.get_world_folders()
        
        self.assertIn("world", worlds)
    
    def test_get_world_folders_ignores_non_worlds(self):
        """Should not include folders without level.dat"""
        # Create a non-world folder
        os.makedirs(os.path.join(self.test_dir, "plugins"))
        
        worlds = self.backup.get_world_folders()
        
        self.assertNotIn("plugins", worlds)
    
    def test_create_backup_success(self):
        """Should create tar.gz backup of world folders"""
        success, msg = self.backup.create_backup()
        
        self.assertTrue(success)
        
        # Verify backup file exists
        backup_dir = os.path.join(self.test_dir, "backups")
        backups = os.listdir(backup_dir)
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].endswith(".tar.gz"))
        self.assertIn("1.21.4", backups[0])
    
    def test_create_backup_no_worlds(self):
        """Should fail if no world folders exist"""
        # Remove world folder
        shutil.rmtree(self.world_dir)
        
        success, msg = self.backup.create_backup()
        
        self.assertFalse(success)
        self.assertIn("no world", msg.lower())
    
    def test_backup_contains_world_data(self):
        """Backup archive should contain world files"""
        self.backup.create_backup()
        
        backup_dir = os.path.join(self.test_dir, "backups")
        backup_file = os.path.join(backup_dir, os.listdir(backup_dir)[0])
        
        with tarfile.open(backup_file, 'r:gz') as tar:
            names = tar.getnames()
        
        self.assertIn("world", names)
        self.assertTrue(any("level.dat" in n for n in names))
    
    def test_cleanup_old_backups(self):
        """Should remove old backups exceeding max_backups"""
        self.config.set("max_backups", 3)
        
        # Create backup directory and 5 fake backup files directly
        # (bypassing create_backup to avoid cleanup during creation)
        backup_dir = os.path.join(self.test_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        import time
        for i in range(5):
            backup_name = f"backup_1.21.4_{20240101_120000 + i}.tar.gz"
            backup_path = os.path.join(backup_dir, backup_name)
            with tarfile.open(backup_path, "w:gz") as tar:
                tar.add(self.world_dir, arcname="world")
            # Touch file to set different mtime
            os.utime(backup_path, (time.time() + i, time.time() + i))
        
        # Verify 5 backups exist before cleanup
        self.assertEqual(len(os.listdir(backup_dir)), 5)
        
        # Trigger cleanup by creating one more backup
        self.backup.create_backup()
        
        backups = self.backup.list_backups()
        self.assertEqual(len(backups), 3)
    
    def test_list_backups_sorted(self):
        """Should list backups newest first"""
        import time
        
        for i in range(3):
            self.backup.create_backup()
            time.sleep(0.1)
        
        backups = self.backup.list_backups()
        
        # Verify sorted by date descending
        dates = [b["date"] for b in backups]
        self.assertEqual(dates, sorted(dates, reverse=True))


class TestMinecraftServerInstall(unittest.TestCase):
    """Tests for server installation"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = Config(self.test_dir)
        self.server = MinecraftServer(self.config)
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('urllib.request.urlopen')
    def test_install_creates_eula(self, mock_urlopen):
        """Installation should create eula.txt with eula=true"""
        # Mock version manifest response
        version_data = {"downloads": {"server": {"url": "https://example.com/server.jar"}}}
        
        # Mock jar download
        jar_content = b"fake jar content"
        
        def mock_urlopen_handler(url, *args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            
            if "server.jar" in url:
                mock_resp.read.side_effect = [jar_content, b""]
                mock_resp.headers = {"content-length": str(len(jar_content))}
            else:
                mock_resp.read.return_value = json.dumps(version_data).encode()
            
            return mock_resp
        
        mock_urlopen.side_effect = mock_urlopen_handler
        
        with patch('json.load', return_value=version_data):
            success, msg = self.server.install("1.21.4", "https://example.com/1.21.4.json", 8)
        
        self.assertTrue(success)
        
        # Verify EULA
        eula_path = os.path.join(self.test_dir, "eula.txt")
        self.assertTrue(os.path.exists(eula_path))
        with open(eula_path) as f:
            content = f.read()
        self.assertIn("eula=true", content)
    
    @patch('urllib.request.urlopen')
    def test_install_updates_config(self, mock_urlopen):
        """Installation should update config with version and RAM"""
        version_data = {"downloads": {"server": {"url": "https://example.com/server.jar"}}}
        
        def mock_urlopen_handler(url, *args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.side_effect = [b"jar", b""]
            mock_resp.headers = {"content-length": "3"}
            return mock_resp
        
        mock_urlopen.side_effect = mock_urlopen_handler
        
        with patch('json.load', return_value=version_data):
            self.server.install("1.21.4", "https://example.com/1.21.4.json", 16)
        
        self.assertEqual(self.config.get("current_version"), "1.21.4")
        self.assertEqual(self.config.get("ram_gb"), 16)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and error handling"""
    
    def test_config_with_nonexistent_directory(self):
        """Config should handle non-existent directory gracefully"""
        config = Config("/nonexistent/path/that/doesnt/exist")
        
        # Should work with defaults
        self.assertEqual(config.get("ram_gb"), 4)
    
    def test_backup_manager_empty_server_dir(self):
        """BackupManager should handle empty server directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(tmpdir)
            backup = BackupManager(config)
            
            worlds = backup.get_world_folders()
            self.assertEqual(worlds, [])
    
    def test_server_status_no_jar(self):
        """get_status should show not installed when no jar"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(tmpdir)
            server = MinecraftServer(config)
            
            status = server.get_status()
            
            self.assertFalse(status["installed"])
    
    @patch('subprocess.run')
    def test_command_history_no_duplicates(self, mock_run):
        """Same command shouldn't create duplicate history entries"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(tmpdir)
            server = MinecraftServer(config)
            session_name = config.get_session_name()
            
            mock_run.return_value = MagicMock(stdout=f"12345.{session_name}")
            
            server.send_command("say test")
            server.send_command("say test")
            server.send_command("say test")
            
            history = config.get("command_history", [])
            self.assertEqual(history.count("say test"), 1)


class TestGracefulStop(unittest.TestCase):
    """Tests for graceful stop logic with timeout handling"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = Config(self.test_dir)
        self.server = MinecraftServer(self.config)
        self.session_name = self.config.get_session_name()
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('time.sleep')
    @patch('subprocess.run')
    def test_graceful_stop_sends_stop_command(self, mock_run, mock_sleep):
        """Graceful stop should send 'stop' via screen"""
        # First call: is_running returns True
        # Second call: send stop command
        # Subsequent calls: is_running returns False (server stopped)
        session_name = self.session_name
        call_count = [0]
        
        def mock_run_handler(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:  # is_running check
                result.stdout = f"12345.{session_name}"
            elif call_count[0] == 2:  # stop command
                pass
            else:  # subsequent is_running checks
                result.stdout = "No Sockets found"
            return result
        
        mock_run.side_effect = mock_run_handler
        
        success, msg = self.server.stop(graceful=True)
        
        self.assertTrue(success)
        self.assertIn("gracefully", msg.lower())
        
        # Verify stop command was sent
        stop_call = mock_run.call_args_list[1]
        cmd = stop_call[0][0]
        self.assertIn("stuff", cmd)
        self.assertIn("stop\n", cmd)
    
    @patch('time.sleep')
    @patch('subprocess.run')
    def test_graceful_stop_timeout(self, mock_run, mock_sleep):
        """Should fail if server doesn't stop within timeout"""
        # Server always reports running
        mock_run.return_value = MagicMock(stdout=f"12345.{self.session_name}")
        
        success, msg = self.server.stop(graceful=True)
        
        self.assertFalse(success)
        self.assertIn("did not stop", msg.lower())
        
        # Verify we waited (sleep was called 30 times)
        self.assertEqual(mock_sleep.call_count, 30)
    
    @patch('subprocess.run')
    def test_force_stop_uses_quit(self, mock_run):
        """Force stop should use screen -X quit"""
        mock_run.side_effect = [
            MagicMock(stdout=f"12345.{self.session_name}"),  # is_running
            MagicMock()  # quit command
        ]
        
        success, msg = self.server.stop(graceful=False)
        
        self.assertTrue(success)
        self.assertIn("terminated", msg.lower())
        
        quit_call = mock_run.call_args_list[1]
        cmd = quit_call[0][0]
        self.assertIn("quit", cmd)


class TestPaperAPI(unittest.TestCase):
    """Tests for Paper API integration"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = Config(self.test_dir)
        self.server = MinecraftServer(self.config)
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('urllib.request.urlopen')
    def test_fetch_paper_versions(self, mock_urlopen):
        """Should fetch Paper versions from PaperMC API"""
        fake_response = {"versions": ["1.20.4", "1.20.6", "1.21", "1.21.1", "1.21.4"]}
        
        with patch('json.load', return_value=fake_response):
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            
            versions = self.server.fetch_paper_versions()
        
        self.assertEqual(versions, ["1.20.4", "1.20.6", "1.21", "1.21.1", "1.21.4"])
    
    @patch('urllib.request.urlopen')
    def test_fetch_paper_versions_network_error(self, mock_urlopen):
        """Should return empty list on network failure"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Network error")
        
        versions = self.server.fetch_paper_versions()
        
        self.assertEqual(versions, [])
    
    @patch('urllib.request.urlopen')
    def test_get_paper_build(self, mock_urlopen):
        """Should get latest build number for a version"""
        fake_response = {"builds": [100, 101, 102, 150]}
        
        with patch('json.load', return_value=fake_response):
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            
            build = self.server.get_paper_build("1.21.4")
        
        self.assertEqual(build, 150)  # Latest build
    
    @patch('urllib.request.urlopen')
    def test_get_paper_build_no_builds(self, mock_urlopen):
        """Should return None if no builds available"""
        fake_response = {"builds": []}
        
        with patch('json.load', return_value=fake_response):
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            
            build = self.server.get_paper_build("1.21.4")
        
        self.assertIsNone(build)
    
    @patch('urllib.request.urlopen')
    def test_get_paper_jar_url(self, mock_urlopen):
        """Should construct correct Paper jar download URL"""
        fake_response = {
            "downloads": {
                "application": {"name": "paper-1.21.4-150.jar"}
            }
        }
        
        with patch('json.load', return_value=fake_response):
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            
            url = self.server.get_paper_jar_url("1.21.4", 150)
        
        self.assertIn("1.21.4", url)
        self.assertIn("150", url)
        self.assertIn("paper-1.21.4-150.jar", url)
    
    @patch('urllib.request.urlopen')
    def test_install_paper_sets_server_type(self, mock_urlopen):
        """Paper install should set server_type to 'paper'"""
        call_count = [0]
        
        def mock_urlopen_handler(url, *args, **kwargs):
            call_count[0] += 1
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.side_effect = [b"jar", b""]
            mock_resp.headers = {"content-length": "3"}
            return mock_resp
        
        mock_urlopen.side_effect = mock_urlopen_handler
        
        with patch.object(self.server, 'get_paper_build', return_value=150):
            with patch.object(self.server, 'get_paper_jar_url', 
                            return_value="https://example.com/paper.jar"):
                self.server.install_paper("1.21.4", 8)
        
        self.assertEqual(self.config.get("server_type"), "paper")
        self.assertEqual(self.config.get("current_version"), "1.21.4")


class TestVersionSwitching(unittest.TestCase):
    """Tests for version switching with backup"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = Config(self.test_dir)
        self.config.set("current_version", "1.21.3")
        self.config.set("server_type", "vanilla")
        self.server = MinecraftServer(self.config)
        self.backup = BackupManager(self.config)
        
        # Create fake world
        self.world_dir = os.path.join(self.test_dir, "world")
        os.makedirs(self.world_dir)
        with open(os.path.join(self.world_dir, "level.dat"), 'w') as f:
            f.write("world data")
        
        # Create existing server.jar
        with open(os.path.join(self.test_dir, "server.jar"), 'wb') as f:
            f.write(b"old jar")
    
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_version_switch_preserves_world(self):
        """Version switch should preserve world folder"""
        # Simulate version switch by reinstalling
        with patch.object(self.server, 'get_server_jar_url', 
                         return_value="https://example.com/new.jar"):
            with patch.object(self.server, 'download_file', return_value=True):
                success, msg = self.server.install("1.21.4", "url", 8)
        
        # World should still exist
        self.assertTrue(os.path.exists(self.world_dir))
        self.assertTrue(os.path.exists(os.path.join(self.world_dir, "level.dat")))
    
    def test_backup_before_version_switch(self):
        """Should be able to create backup before switching"""
        # Create backup
        success, msg = self.backup.create_backup()
        self.assertTrue(success)
        
        # Verify backup contains world
        backups = self.backup.list_backups()
        self.assertEqual(len(backups), 1)
        self.assertIn("1.21.3", backups[0]["name"])  # Old version in backup name
    
    def test_version_switch_updates_config(self):
        """Version switch should update config to new version"""
        with patch.object(self.server, 'get_server_jar_url', 
                         return_value="https://example.com/new.jar"):
            with patch.object(self.server, 'download_file', return_value=True):
                self.server.install("1.21.4", "url", 8)
        
        self.assertEqual(self.config.get("current_version"), "1.21.4")
    
    def test_server_jar_replaced(self):
        """Version switch should replace server.jar"""
        jar_path = os.path.join(self.test_dir, "server.jar")
        old_content = open(jar_path, 'rb').read()
        
        def mock_download(url, dest, callback=None):
            with open(dest, 'wb') as f:
                f.write(b"new jar content")
            return True
        
        with patch.object(self.server, 'get_server_jar_url', 
                         return_value="https://example.com/new.jar"):
            with patch.object(self.server, 'download_file', side_effect=mock_download):
                self.server.install("1.21.4", "url", 8)
        
        new_content = open(jar_path, 'rb').read()
        self.assertNotEqual(old_content, new_content)
        self.assertEqual(new_content, b"new jar content")


if __name__ == "__main__":
    unittest.main(verbosity=2)


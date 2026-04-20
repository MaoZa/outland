import pytest
from unittest.mock import MagicMock, patch


class TestDockerManager:
    @pytest.fixture
    def docker_manager(self):
        from agent.services.docker_manager import DockerManager
        return DockerManager()

    def test_spawn_container(self, docker_manager):
        with patch("agent.services.docker_manager.docker") as mock_docker:
            mock_container = MagicMock()
            mock_container.name = "test-container"
            mock_container.id = "abc123"
            mock_container.ports = {"5555/tcp": [{"HostPort": "5555"}]}
            mock_container.status = "running"
            mock_docker.from_env.return_value.containers.run.return_value = mock_container

            result = docker_manager.spawn_container(
                width=720,
                height=1280,
                fps=30,
                device_model="test_model"
            )

            assert result["success"] is True
            assert result["container_id"] == "abc123"

    def test_delete_container(self, docker_manager):
        with patch("agent.services.docker_manager.docker") as mock_docker:
            mock_container = MagicMock()
            mock_docker.from_env.return_value.containers.get.return_value = mock_container

            result = docker_manager.delete_container("test-container", force=True)

            assert result["success"] is True
            mock_container.remove.assert_called_once_with(force=True)

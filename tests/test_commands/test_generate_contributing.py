# built-in
from textwrap import dedent

# project
from dephell.commands import GenerateContributingCommand
from dephell.config import Config


def test_make_contributing_pytest(temp_path):
    (temp_path / 'pyproject.toml').write_text(dedent(
        """
        [tool.dephell.isort]
        command = "isort -y"

        [tool.dephell.flake8]
        command = "flake8"

        [tool.dephell.pytest]
        command = "python -m pytest tests/"
        """,
    ))
    config = Config()
    config.attach({'project': str(temp_path)})
    command = GenerateContributingCommand(argv=[], config=config)
    result = command()

    assert result is True
    assert (temp_path / command.COMMAND_TITLE).exists()
    content = (temp_path / command.COMMAND_TITLE).read_text()
    assert 'isort' in content
    assert 'python -m pytest tests/' in content

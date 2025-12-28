from infrahub_sdk.schema.repository import InfrahubRepositoryConfig


def test_generator(repository_config: InfrahubRepositoryConfig) -> None:
    generator = repository_config.get_generator_definition("dedicated_internet_generator")
    generator_class = generator.load_class()

    assert generator_class is not None

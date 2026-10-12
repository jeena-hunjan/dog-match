"""Raw data sources: where each file comes from and where it is cached under data/raw/."""

from dataclasses import dataclass

_STANFORD = "http://vision.stanford.edu/aditya86/ImageNetDogs"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    filename: str  # relative to the raw data directory
    api_key_env: str | None = None  # sent as the x-api-key header, read from this env var
    extract: bool = False  # unpack the tar archive into a folder next to it


DOG_API_BREEDS = Source(
    name="dog_api_breeds",
    url="https://api.thedogapi.com/v1/breeds",
    filename="dog_api/breeds.json",
    api_key_env="DOG_API_KEY",  # pragma: allowlist secret (env var name, not a key)
)
# Official train/test split and the 120 class folder names (MATLAB .mat files).
STANFORD_LISTS = Source(
    name="stanford_lists",
    url=f"{_STANFORD}/lists.tar",
    filename="stanford/lists.tar",
    extract=True,
)

BREED_SOURCES: tuple[Source, ...] = (
    DOG_API_BREEDS,
    STANFORD_LISTS,
)

_OXFORD = "https://www.robots.ox.ac.uk/~vgg/data/pets/data"

# Large image archives (~1.6 GB together). Never committed: the licences forbid it.
STANFORD_IMAGES = Source(
    name="stanford_images",
    url=f"{_STANFORD}/images.tar",
    filename="stanford/images.tar",
    extract=True,
)
# Oxford-IIIT Pet: external test set (dogs) and not-a-dog checks (cats) only.
OXFORD_IMAGES = Source(
    name="oxford_images",
    url=f"{_OXFORD}/images.tar.gz",
    filename="oxford/images.tar.gz",
    extract=True,
)
OXFORD_ANNOTATIONS = Source(
    name="oxford_annotations",
    url=f"{_OXFORD}/annotations.tar.gz",
    filename="oxford/annotations.tar.gz",
    extract=True,
)

IMAGE_SOURCES: tuple[Source, ...] = (STANFORD_IMAGES, OXFORD_IMAGES, OXFORD_ANNOTATIONS)

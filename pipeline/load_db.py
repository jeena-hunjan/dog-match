"""Load breeds, traits and country restrictions into Postgres. Safe to re-run.

Breeds are upserted by name, so their ids stay stable once requests and recommendations
refer to them. A breed that disappears from the sources is reported but not deleted,
because logged requests may still point at it. Traits of the loaded breeds and all
restrictions are replaced, since nothing references them.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Breed, BreedTrait, CountryRestriction
from pipeline.breed_data import BreedRecord, TraitRecord
from pipeline.restrictions import Restriction


@dataclass(frozen=True)
class LoadSummary:
    breeds: int
    traits: int
    restrictions: int
    stale_breeds: list[str]  # in the database but no longer in the sources


def load(
    session: Session,
    breeds: Sequence[BreedRecord],
    traits: Sequence[TraitRecord],
    restrictions: Sequence[Restriction],
) -> LoadSummary:
    """Write everything in the caller's transaction; the caller commits."""
    rows = [asdict(b) for b in breeds]
    upsert = insert(Breed).values(rows)
    session.execute(
        upsert.on_conflict_do_update(
            index_elements=[Breed.name],
            set_={key: upsert.excluded[key] for key in rows[0] if key != "name"},
        )
    )

    ids: dict[str, int] = {name: id_ for name, id_ in session.execute(select(Breed.name, Breed.id))}
    loaded = {b.name for b in breeds}

    session.execute(delete(BreedTrait).where(BreedTrait.breed_id.in_([ids[n] for n in loaded])))
    if traits:
        session.execute(
            insert(BreedTrait),
            [{"breed_id": ids[t.breed], "trait": t.trait, "score": t.score} for t in traits],
        )

    session.execute(delete(CountryRestriction))
    if restrictions:
        session.execute(
            insert(CountryRestriction),
            [
                {
                    "country": r.country,
                    "breed_id": ids[r.breed],
                    "status": r.status,
                    "source_url": r.source_url,
                    "last_checked": r.last_checked,
                }
                for r in restrictions
            ],
        )

    return LoadSummary(
        breeds=len(breeds),
        traits=len(traits),
        restrictions=len(restrictions),
        stale_breeds=sorted(set(ids) - loaded),
    )

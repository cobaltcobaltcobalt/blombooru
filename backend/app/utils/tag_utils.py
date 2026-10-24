import fnmatch
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

if TYPE_CHECKING:
    from ..models import Tag

def resolve_aliases(db: Session, raw_names: list[str]) -> dict[str, tuple[str, str]]:
    """Build an alias lookup map for a list of (already lowercased) tag names."""
    from ..models import TagAlias

    if not raw_names:
        return {}

    aliases = db.query(TagAlias).filter(TagAlias.alias_name.in_(raw_names)).all()
    return {
        a.alias_name: (a.target_tag.name, a.target_tag.category)
        for a in aliases
    }

def _build_rule_trigger_groups(
    base_names: list[str],
    patterns: list[str] | None,
    active_names: set[str],
) -> list[list[str]]:
    """Build sorted trigger tag name groups for a matched TagImplication rule."""
    if not patterns:
        group = sorted(set(base_names))
        return [group] if group else []

    import itertools
    import math

    pattern_matches_list: list[list[str]] = []
    for pat in patterns:
        matched = sorted(name for name in active_names if fnmatch.fnmatch(name, pat))
        if not matched:
            return []
        pattern_matches_list.append(matched)

    total_combos = math.prod(len(m) for m in pattern_matches_list)
    if total_combos <= 16:
        groups: list[list[str]] = []
        for combo in itertools.product(*pattern_matches_list):
            group = sorted(set(base_names) | set(combo))
            if group and group not in groups:
                groups.append(group)
        return groups

    combined = set(base_names)
    for matched in pattern_matches_list:
        combined.update(matched)
    return [sorted(combined)] if combined else []


def _expand_implications_with_sources(
    db: Session,
    tags: Iterable["Tag"],
    *,
    max_depth: int,
    extra_names: Iterable[str] = (),
    seed_trigger_names: set[str] | None = None,
) -> tuple[list["Tag"], dict[str, list[list[str]]]]:
    """
    Recursively expand all tag implications given a collection of Tag objects
    (and optional extra tag names not yet persisted as Tag rows).
    Returns (newly_implied_tags, implied_by_map) where implied_by_map maps
    each newly implied tag name to a list of trigger tag groups.
    """
    from collections import defaultdict
    from ..models import Tag, TagImplication, blombooru_implication_targets
    from ..utils.logger import logger

    initial_tags = set(tags) if tags else set()
    extra_name_set = {n.strip().lower() for n in (extra_names or ()) if n and n.strip()}
    if not initial_tags and not extra_name_set:
        return [], {}

    eligible_triggers: set[str] | None = None
    if seed_trigger_names is not None:
        eligible_triggers = {n.strip().lower() for n in seed_trigger_names if n and n.strip()}
        if not eligible_triggers:
            return [], {}

    start_time = time.perf_counter()

    active_tags = set(initial_tags)
    initial_ids: set[int] = {tag.id for tag in initial_tags}
    active_ids: set[int] = set(initial_ids)
    initial_names_lower: set[str] = {tag.name.lower() for tag in initial_tags} | extra_name_set

    implied_by_map: dict[str, list[list[str]]] = defaultdict(list)
    ancestors: dict[str, set[str]] = defaultdict(set)

    # Fetch standalone pattern rules (implications with wildcard patterns but no target tags)
    pattern_only_rules = db.execute(
        select(TagImplication)
        .where(
            TagImplication.target_tag_patterns.is_not(None),
            ~TagImplication.target_tags.any(),
        )
        .options(selectinload(TagImplication.implied_tags))
    ).scalars().all()

    applied_implications: set[int] = set()
    depth_reached = 0

    def _record_rule_application(
        rule: TagImplication,
        active_names: set[str],
        newly_implied: set[Tag],
    ) -> tuple[bool, bool]:
        base_names = [t.name for t in rule.target_tags] if rule.target_tags else []
        groups = _build_rule_trigger_groups(base_names, rule.target_tag_patterns, active_names)
        if eligible_triggers is not None:
            groups = [grp for grp in groups if any(t.lower() in eligible_triggers for t in grp)]
        if not groups:
            return False, False

        rule_ancestors: set[str] = set()
        for grp in groups:
            for trig_name in grp:
                rule_ancestors.add(trig_name)
                rule_ancestors.update(ancestors.get(trig_name, ()))

        added_attribution = False
        for imp_tag in rule.implied_tags:
            if imp_tag.id in initial_ids or imp_tag.name.lower() in initial_names_lower:
                continue
            if imp_tag.name in rule_ancestors:
                continue
            newly_implied.add(imp_tag)
            if eligible_triggers is not None:
                eligible_triggers.add(imp_tag.name.lower())
            existing_groups = implied_by_map[imp_tag.name]
            for grp in groups:
                if imp_tag.name in grp:
                    continue
                if grp not in existing_groups:
                    existing_groups.append(grp)
                    added_attribution = True
            ancestors[imp_tag.name].update(rule_ancestors)
        return True, added_attribution

    for depth in range(max_depth):
        depth_reached = depth
        newly_implied: set[Tag] = set()
        active_names: set[str] = {tag.name for tag in active_tags} | extra_name_set
        added_any_attribution = False

        # Evaluate pattern-only implications against current tag names
        for rule in pattern_only_rules:
            if rule.id in applied_implications:
                continue
            patterns = rule.target_tag_patterns or []
            if patterns and all(any(fnmatch.fnmatch(name, pat) for name in active_names) for pat in patterns):
                fired, added_attr = _record_rule_application(rule, active_names, newly_implied)
                if fired:
                    applied_implications.add(rule.id)
                if added_attr:
                    added_any_attribution = True

        # Evaluate target-tag implications targeting any current tag IDs
        if active_ids:
            stmt = (
                select(TagImplication)
                .join(
                    blombooru_implication_targets,
                    TagImplication.id == blombooru_implication_targets.c.implication_id,
                )
                .where(
                    blombooru_implication_targets.c.tag_id.in_(active_ids),
                )
                .options(
                    selectinload(TagImplication.target_tags),
                    selectinload(TagImplication.implied_tags),
                )
                .distinct()
            )
            if applied_implications:
                stmt = stmt.where(~TagImplication.id.in_(applied_implications))

            candidates = db.execute(stmt).scalars().all()

            for rule in candidates:
                if rule.id in applied_implications:
                    continue

                # Every target tag must be present in the active ID set
                if not all(t.id in active_ids for t in rule.target_tags):
                    continue

                # Any associated pattern constraints must also be satisfied
                patterns = rule.target_tag_patterns
                if patterns:
                    if not all(any(fnmatch.fnmatch(name, pat) for name in active_names) for pat in patterns):
                        continue

                fired, added_attr = _record_rule_application(rule, active_names, newly_implied)
                if fired:
                    applied_implications.add(rule.id)
                if added_attr:
                    added_any_attribution = True

        # Determine if any genuinely new tags were introduced in this pass
        new_ids = {t.id for t in newly_implied if t.id not in active_ids}

        if not new_ids and not added_any_attribution:
            break

        active_tags.update(newly_implied)
        active_ids.update(new_ids)
        if not new_ids:
            break

    logger.debug(
        f"Implication expansion finished in {time.perf_counter() - start_time:.3f}s "
        f"(depth={depth_reached}, implied={len(active_tags) - len(initial_tags)})"
    )
    implied_list = [tag for tag in active_tags - initial_tags if tag.name.lower() not in initial_names_lower]
    return implied_list, dict(implied_by_map)

def _expand_implications(db: Session, tags: Iterable["Tag"], *, max_depth: int) -> list["Tag"]:
    """
    Recursively expand all tag implications given a list of tags.
    Returns all tags that were not in the original input.
    """
    implied_tags, _ = _expand_implications_with_sources(db, tags, max_depth=max_depth)
    return implied_tags

def expand_implications(
    db: Session,
    tag_set: dict[int, "Tag"],
    *,
    extra_names: Iterable[str] = (),
    seed_trigger_names: set[str] | None = None,
) -> dict[str, list[list[str]]]:
    """Recursively expand tag implications into *tag_set*, mutating it in place and returning implied_by map."""
    if not tag_set and not extra_names:
        return {}

    implied_tags, implied_by_map = _expand_implications_with_sources(
        db,
        tag_set.values(),
        max_depth=1_000,
        extra_names=extra_names,
        seed_trigger_names=seed_trigger_names,
    )
    tag_set |= {t.id: t for t in implied_tags}
    return implied_by_map

def resolve_implications_with_sources(
    db: Session,
    tags: list[str],
    max_depth: int = 10,
    seed_tags: list[str] | None = None,
) -> tuple[list[str], dict[str, list[list[str]]]]:
    """
    Recursively resolve all tag implications for a given list of tag names,
    returning (sorted_implied_tag_names, implied_by_map).
    """
    if not tags:
        return [], {}

    from ..models import Tag

    initial_raw = {t.strip().lower() for t in tags if t and t.strip()}
    if not initial_raw:
        return [], {}

    seed_raw: set[str] | None = None
    if seed_tags is not None:
        seed_raw = {t.strip().lower() for t in seed_tags if t and t.strip()}
        if not seed_raw:
            return [], {}

    all_raw = initial_raw | (seed_raw or set())
    alias_map = resolve_aliases(db, list(all_raw))
    initial_names = {alias_map[t][0].lower() if t in alias_map else t for t in initial_raw}

    seed_names: set[str] | None = None
    if seed_raw is not None:
        seed_names = {alias_map[t][0].lower() if t in alias_map else t for t in seed_raw}

    # Resolve database IDs for any known tags in the initial set
    initial_tags: set[Tag] = set(db.scalars(
        select(Tag).where(Tag.name.in_(initial_names))
    ).all())

    known_names = {t.name.lower() for t in initial_tags}
    extra_names = initial_names - known_names

    implied_tags, implied_by_map = _expand_implications_with_sources(
        db,
        initial_tags,
        max_depth=max_depth,
        extra_names=extra_names,
        seed_trigger_names=seed_names,
    )

    return sorted(tag.name for tag in implied_tags), implied_by_map

def resolve_implications(db: Session, tags: list[str], max_depth: int = 10) -> list[str]:
    """
    Recursively resolve all tag implications for a given list of tag names.
    Returns the names of all implied tags that were not in the original input.
    """
    implied_names, _ = resolve_implications_with_sources(db, tags, max_depth=max_depth)
    return implied_names

def convert_implied_by_names_to_ids(
    db: Session,
    implied_by_name: dict[str, list[list[str]]],
    tag_set: dict[int, "Tag"],
) -> dict[int, list[list[int]]]:
    """Convert a tag_name -> [[trigger_name, ...]] map into tag_id -> [[trigger_id, ...]]."""
    if not implied_by_name:
        return {}

    from ..models import Tag

    name_to_id: dict[str, int] = {t.name.lower(): t.id for t in tag_set.values()}
    missing_names: set[str] = set()
    for imp_name, groups in implied_by_name.items():
        if imp_name.lower() not in name_to_id:
            missing_names.add(imp_name.lower())
        for grp in groups:
            if isinstance(grp, list):
                for item in grp:
                    if isinstance(item, str) and item.strip().lower() not in name_to_id:
                        missing_names.add(item.strip().lower())

    if missing_names:
        for tid, tname in db.query(Tag.id, Tag.name).filter(Tag.name.in_(missing_names)).all():
            name_to_id[tname.lower()] = tid

    result: dict[int, list[list[int]]] = {}
    for imp_name, groups in implied_by_name.items():
        imp_tid = name_to_id.get(imp_name.lower())
        if not imp_tid:
            continue
        id_groups: list[list[int]] = []
        for grp in groups:
            if not isinstance(grp, list):
                continue
            ids_in_grp: list[int] = []
            for item in grp:
                if isinstance(item, int) and not isinstance(item, bool):
                    ids_in_grp.append(item)
                elif isinstance(item, str):
                    trig_id = name_to_id.get(item.strip().lower())
                    if trig_id:
                        ids_in_grp.append(trig_id)
            cleaned = sorted(set(ids_in_grp))
            if cleaned and cleaned not in id_groups:
                id_groups.append(cleaned)
        result[imp_tid] = id_groups
    return result

def validate_and_resolve_implied_by_ids(
    db: Session,
    candidate_tags_by_id: dict[int, "Tag"],
    client_implied_tags: dict[str, list[list[str]]] | None,
) -> dict[int, list[list[int]]]:
    """
    Validate client-supplied implied_tags against active TagImplication rules in the database
    and return a mapping of implied_tag_id -> list of trigger tag ID groups (list[list[int]]).
    Entries that do not match any real implication rule are rejected.
    """
    if not client_implied_tags or not candidate_tags_by_id:
        return {}

    from collections import defaultdict
    from ..models import Tag, TagImplication, blombooru_implication_implied

    all_raw_names: set[str] = set()
    for raw_k, groups in client_implied_tags.items():
        if raw_k and str(raw_k).strip():
            all_raw_names.add(str(raw_k).strip().lower())
        if isinstance(groups, list):
            for grp in groups:
                if isinstance(grp, list):
                    for item in grp:
                        if isinstance(item, str) and item.strip():
                            all_raw_names.add(item.strip().lower())

    if not all_raw_names:
        return {}

    alias_map = resolve_aliases(db, list(all_raw_names))
    canon_names: set[str] = {
        alias_map[n][0].lower() if n in alias_map else n for n in all_raw_names
    }

    name_to_tag: dict[str, Tag] = {t.name.lower(): t for t in candidate_tags_by_id.values()}
    missing_canon = canon_names - set(name_to_tag.keys())
    if missing_canon:
        for t in db.query(Tag).filter(Tag.name.in_(missing_canon)).all():
            name_to_tag[t.name.lower()] = t

    candidate_implied_ids: set[int] = set()
    normalized_requests: dict[int, list[list[str]]] = defaultdict(list)
    has_empty_group_request: set[int] = set()

    for raw_k, groups in client_implied_tags.items():
        if not raw_k or not str(raw_k).strip():
            continue
        norm_k = str(raw_k).strip().lower()
        canon_k = alias_map[norm_k][0].lower() if norm_k in alias_map else norm_k
        imp_tag = name_to_tag.get(canon_k)
        if not imp_tag or imp_tag.id not in candidate_tags_by_id:
            continue
        candidate_implied_ids.add(imp_tag.id)
        if not groups:
            has_empty_group_request.add(imp_tag.id)
            continue
        if isinstance(groups, list):
            for grp in groups:
                if isinstance(grp, list):
                    cleaned_names: list[str] = []
                    valid_grp = True
                    for item in grp:
                        if isinstance(item, int) and not isinstance(item, bool):
                            # Resolve int ID if present
                            found_t = candidate_tags_by_id.get(item) or db.query(Tag).filter(Tag.id == item).first()
                            if not found_t:
                                valid_grp = False
                                break
                            name_to_tag[found_t.name.lower()] = found_t
                            cleaned_names.append(found_t.name.lower())
                        elif isinstance(item, str) and item.strip():
                            n_low = item.strip().lower()
                            c_low = alias_map[n_low][0].lower() if n_low in alias_map else n_low
                            if c_low not in name_to_tag:
                                valid_grp = False
                                break
                            cleaned_names.append(c_low)
                    if valid_grp and cleaned_names:
                        dedup_grp = sorted(set(cleaned_names))
                        if dedup_grp not in normalized_requests[imp_tag.id]:
                            normalized_requests[imp_tag.id].append(dedup_grp)

    if not candidate_implied_ids:
        return {}

    stmt = (
        select(TagImplication)
        .join(
            blombooru_implication_implied,
            TagImplication.id == blombooru_implication_implied.c.implication_id,
        )
        .where(blombooru_implication_implied.c.tag_id.in_(candidate_implied_ids))
        .options(
            selectinload(TagImplication.target_tags),
            selectinload(TagImplication.implied_tags),
        )
        .distinct()
    )
    rules = db.execute(stmt).scalars().all()
    rules_by_implied_id: dict[int, list[TagImplication]] = defaultdict(list)
    for rule in rules:
        for imp_t in rule.implied_tags:
            if imp_t.id in candidate_implied_ids:
                rules_by_implied_id[imp_t.id].append(rule)

    validated: dict[int, list[list[int]]] = {}
    post_tag_names = {t.name.lower() for t in candidate_tags_by_id.values()}

    for imp_tid in candidate_implied_ids:
        matching_rules = rules_by_implied_id.get(imp_tid, [])
        if not matching_rules:
            continue
        imp_tag_name = candidate_tags_by_id[imp_tid].name.lower()
        valid_id_groups: list[list[int]] = []

        for req_grp in normalized_requests.get(imp_tid, []):
            if imp_tag_name in req_grp:
                continue
            grp_set = set(req_grp)
            is_valid = False
            for rule in matching_rules:
                base_names = [t.name.lower() for t in rule.target_tags] if rule.target_tags else []
                if not all(bn in grp_set for bn in base_names):
                    continue
                built = _build_rule_trigger_groups(base_names, rule.target_tag_patterns, grp_set)
                if req_grp in built:
                    is_valid = True
                    break
            if is_valid:
                id_grp = sorted({name_to_tag[n].id for n in req_grp if n in name_to_tag})
                if id_grp and id_grp not in valid_id_groups:
                    valid_id_groups.append(id_grp)

        if not valid_id_groups and imp_tid in has_empty_group_request:
            other_post_names = post_tag_names - {imp_tag_name}
            for rule in matching_rules:
                base_names = [t.name.lower() for t in rule.target_tags] if rule.target_tags else []
                if not all(bn in other_post_names for bn in base_names):
                    continue
                for built_grp in _build_rule_trigger_groups(base_names, rule.target_tag_patterns, other_post_names):
                    if imp_tag_name in built_grp:
                        continue
                    id_grp = sorted({name_to_tag[n].id for n in built_grp if n in name_to_tag})
                    if id_grp and id_grp not in valid_id_groups:
                        valid_id_groups.append(id_grp)

        if valid_id_groups:
            validated[imp_tid] = valid_id_groups

    return validated

def dtext_to_plain(text: str) -> str:
    """
    Convert Danbooru DText markup to plain readable text.

    Handles the subset of DText used in artist commentaries:
    - [b]...[/b]             - bold; kept as plain text
    - "label":[url]          - named link; rendered as "label (url)"
    - <url>                  - bare URL angle-bracket link; rendered as the URL
    - [i]...[/i]             - italic; kept as plain text
    - [s]...[/s]             - strikethrough; kept as plain text
    - [u]...[/u]             - underline; kept as plain text
    - [tn]...[/tn]           - translator's note; kept as plain text
    - [spoiler]...[/spoiler] - kept as plain text
    - [[wiki_link]]          - double-bracket wiki links; kept as plain text
    - [expand]...[/expand]   - kept as plain text
    """
    import html
    import re

    if not text:
        return ""

    # Named links: "label":[url]  ->  label (url)
    text = re.sub(
        r'"([^"]+?)":\[([^\]]+?)\]',
        lambda m: f'{m.group(1)} ({m.group(2)})',
        text,
    )
    # Named links with plain URL (no brackets): "label":https://...
    text = re.sub(
        r'"([^"]+?)":(https?://\S+)',
        lambda m: f'{m.group(1)} ({m.group(2)})',
        text,
    )
    # Bare angle-bracket URLs: <https://...>  ->  https://...
    text = re.sub(r'<(https?://[^>]+)>', r'\1', text)
    # Strip block/section tags (keep content between them)
    text = re.sub(r'\[section(?:=[^\]]+)?\]|\[/section\]', '', text, flags=re.IGNORECASE)
    # Strip inline formatting tags (keep content)
    text = re.sub(r'\[/?(?:b|i|u|s|tn|spoiler|expand|quote)\]', '', text, flags=re.IGNORECASE)
    # Wiki double-bracket links: [[page_name]] or [[page_name|display]]
    text = re.sub(r'\[\[(?:[^|\]]+\|)?([^\]]+)\]\]', r'\1', text)
    # Decode HTML entities
    text = html.unescape(text)
    # Normalize Windows-style line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return text.strip()

def enrich_and_resolve_tags(
    db: Session,
    tags: list,
    dry_run: bool = True
) -> list:
    """
    Enrich, resolve aliases, match database categories, expand implications, and deduplicate
    a list of tags (which can be BooruTag objects, dicts, or strings).

    Returns a list of BooruTag objects with canonical names, category assignments, and is_new flags.
    """
    if not tags:
        return []

    from sqlalchemy import func
    from ..models import Tag
    from ..services.booru.types import BooruTag

    # Normalize input into (name, category) tuples
    raw_tuples: list[tuple[str, str]] = []
    for item in tags:
        if isinstance(item, BooruTag):
            name = item.name.strip()
            category = item.category or "general"
        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            category = item.get("category") or "general"
        elif isinstance(item, str):
            name = item.strip()
            category = "general"
        else:
            continue

        if name:
            raw_tuples.append((name, category))

    if not raw_tuples:
        return []

    raw_names = [t[0].lower() for t in raw_tuples]
    alias_map = resolve_aliases(db, raw_names)

    canonical_names: set[str] = set()
    for raw in raw_names:
        if raw in alias_map:
            canonical_names.add(alias_map[raw][0].lower())
        else:
            canonical_names.add(raw)

    existing_tags = (
        db.query(Tag)
        .filter(func.lower(Tag.name).in_(canonical_names))
        .all()
    )

    tag_set: dict[int, Tag] = {t.id: t for t in existing_tags}

    expand_implications(db, tag_set)

    seen_canonical: set[str] = set()
    enriched: list[BooruTag] = []

    for name, category in raw_tuples:
        raw = name.lower()
        canonical_name = alias_map[raw][0] if raw in alias_map else name
        c_lower = canonical_name.lower()
        if c_lower in seen_canonical:
            continue
        seen_canonical.add(c_lower)

        existing_match = next((t_obj for t_obj in tag_set.values() if t_obj.name.lower() == c_lower), None)
        if existing_match:
            match_rating = existing_match.rating.value if existing_match.rating else "none"
            enriched.append(BooruTag(
                name=existing_match.name,
                category=existing_match.category,
                is_new=False,
                rating=match_rating
            ))
        else:
            enriched.append(BooruTag(
                name=canonical_name,
                category=category,
                is_new=True,
                rating="none"
            ))

    for implied in tag_set.values():
        if implied.name.lower() not in seen_canonical:
            seen_canonical.add(implied.name.lower())
            implied_rating = implied.rating.value if implied.rating else "none"
            enriched.append(BooruTag(
                name=implied.name,
                category=implied.category,
                is_new=False,
                rating=implied_rating
            ))

    return enriched

def normalize_tag_rating(val):
    """Normalize tag rating to RatingEnum, or None if 'none' or null. Raises HTTPException on invalid input."""
    from fastapi import HTTPException
    from ..enums import RatingEnum

    if val is None:
        return None
    if isinstance(val, RatingEnum):
        return val
    cleaned = str(val).strip().lower()
    if cleaned in ("none", ""):
        return None
    if cleaned in RatingEnum.__members__:
        return RatingEnum[cleaned]
    raise HTTPException(status_code=400, detail=f"Invalid Tag Rating: '{val}'. Accepted values: 'none', 'safe', 'questionable', 'explicit'.")

def apply_tag_rating_filter(query, rating):
    """Apply tag rating filter to a Tag query."""
    from collections.abc import Iterable
    from sqlalchemy import or_
    from ..enums import parse_rating_filter, is_rating_filter_active
    from ..models import Tag

    if not rating:
        return query

    # Guard against non-string, non-iterable objects (e.g. FastAPI Query default param in direct calls)
    if not isinstance(rating, (str, Iterable)):
        return query

    if isinstance(rating, str):
        raw_list = [r.strip().lower() for r in rating.split(",") if r.strip()]
    else:
        raw_list = [str(r).strip().lower() for r in rating if str(r).strip()]

    if not raw_list:
        return query

    has_none = "none" in raw_list
    valid_ratings = parse_rating_filter(rating)

    # If only 'none' was requested (no valid enum ratings)
    if has_none and not valid_ratings:
        return query.filter(Tag.rating.is_(None))

    # If valid ratings are present
    if valid_ratings:
        if not is_rating_filter_active(valid_ratings):
            return query
        return query.filter(or_(Tag.rating.is_(None), Tag.rating.in_(valid_ratings)))

    return query

RATING_HIERARCHY = {
    None: 0,
    "safe": 1,
    "questionable": 2,
    "explicit": 3,
}

HIERARCHY_TO_RATING = {
    1: "safe",
    2: "questionable",
    3: "explicit",
}

def get_escalated_rating(current_rating, tags):
    """Given a media's current rating and a collection of tags, return the escalated RatingEnum if escalated."""
    from ..enums import RatingEnum

    norm_current = RatingEnum.normalize(current_rating) if current_rating is not None else None
    current_key = norm_current.value if norm_current else None
    current_rank = RATING_HIERARCHY.get(current_key, 0)
    max_rank = current_rank

    for tag in tags:
        r = None
        if hasattr(tag, "rating"):
            r = getattr(tag, "rating")
        elif isinstance(tag, dict) and "rating" in tag:
            r = tag["rating"]
        elif isinstance(tag, (RatingEnum, str)):
            r = tag

        norm_tag = RatingEnum.normalize(r) if r is not None else None
        tag_key = norm_tag.value if norm_tag else None
        tag_rank = RATING_HIERARCHY.get(tag_key, 0)
        if tag_rank > max_rank:
            max_rank = tag_rank

    if max_rank > current_rank and max_rank in HIERARCHY_TO_RATING:
        return RatingEnum(HIERARCHY_TO_RATING[max_rank])

    return norm_current

def _tag_name_key(tag):
    """Lowercased name for a Tag model, ProposedTag/BooruTag object, dict or plain string."""
    if isinstance(tag, str):
        name = tag
    elif isinstance(tag, dict):
        name = tag.get("name")
    else:
        name = getattr(tag, "name", None)
    return str(name).strip().lower() if name else None

def get_newly_added_tags(previous_tags, current_tags):
    """Return the entries of current_tags whose name is not present in previous_tags."""
    previous = {k for k in (_tag_name_key(t) for t in (previous_tags or [])) if k}
    newly_added = []
    for tag in current_tags or []:
        key = _tag_name_key(tag)
        if key and key not in previous:
            newly_added.append(tag)
    return newly_added

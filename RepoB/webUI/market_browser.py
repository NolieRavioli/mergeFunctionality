# webUI/market_browser.py

from flask import Blueprint, render_template, request, jsonify
from db.database import get_public_session
from db.models import MarketOrder
from util.sde import (
    load_market_tree,
    load_types_data,
    get_types_in_group,
    resolve_type_ids,
    name_from_type_id,
    _name_to_type_id,
    _type_id_to_name,
)

market_bp = Blueprint("market_browser", __name__, url_prefix="/market")


@market_bp.route("/")
def browser():
    # ensure SDE data is loaded
    load_types_data()
    load_market_tree()

    # --- filters from query params ---
    raw_query     = request.args.get("type_id", "")
    group_id      = request.args.get("group_id", type=int)
    region_id     = request.args.get("region_id", type=int)
    location_id   = request.args.get("location_id", type=int)
    is_buy        = request.args.get("is_buy", type=int)
    sort_by       = request.args.get("sort_by", "price")
    page          = request.args.get("page", 1, type=int)
    page_size     = 50

    # determine the set of type IDs to filter by
    if group_id:
        type_ids = set(get_types_in_group(group_id))
    else:
        type_ids = resolve_type_ids(raw_query)

    # --- build and execute query ---
    session = get_public_session()
    qry = session.query(MarketOrder)
    if type_ids:
        qry = qry.filter(MarketOrder.type_id.in_(type_ids))
    if region_id:
        qry = qry.filter(MarketOrder.region_id == region_id)
    if location_id:
        qry = qry.filter(MarketOrder.location_id == location_id)
    if is_buy in (0, 1):
        qry = qry.filter(MarketOrder.is_buy_order == bool(is_buy))

    if sort_by == "price":
        qry = qry.order_by(MarketOrder.price.asc())
    elif sort_by == "volume":
        qry = qry.order_by(MarketOrder.volume_remain.desc())

    total   = qry.count()
    results = qry.offset((page - 1) * page_size).limit(page_size).all()
    session.close()

    # reload tree for sidebar
    market_tree = load_market_tree()

    return render_template(
        "market_browser.html",
        results=results,
        page=page,
        total=total,
        page_size=page_size,
        query=raw_query,
        selected_group=group_id,
        region_id=region_id,
        location_id=location_id,
        is_buy=is_buy,
        sort_by=sort_by,
        market_tree=market_tree,
        name_from_type_id=name_from_type_id,
    )


@market_bp.route("/autocomplete")
def autocomplete():
    """
    Return up to 10 item‐name suggestions matching the 'q' prefix.
    """
    prefix = request.args.get("q", "").strip().lower()
    suggestions = []
    if prefix:
        load_types_data()
        for name, tid in _name_to_type_id.items():
            if name.startswith(prefix):
                # re‐capitalize via the canonical map
                suggestions.append(_type_id_to_name.get(tid))
                if len(suggestions) >= 10:
                    break

    return jsonify(suggestions)

"""Current season signup identities and staff working assignments."""


def working_accounts(db, season_id):
    return {
        row['tag']: dict(row) for row in db.execute(
            'SELECT s.tag,s.user_id,s.player_name,s.town_hall,s.pool,'
            'r.assigned_clan_tag,c.name AS assigned_clan_name '
            'FROM signups s LEFT JOIN roster_entries r ON r.season_id=s.season_id AND r.tag=s.tag '
            'LEFT JOIN clans c ON c.tag=r.assigned_clan_tag WHERE s.season_id=?',
            (season_id,),
        )
    }

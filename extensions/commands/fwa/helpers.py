from utils.mongo import MongoClient
from utils.classes import FWA
from extensions.commands.clan.dashboard.fwa_data import get_fwa_data

async def get_fwa_base_object(mongo: MongoClient):
    fwa_data = await get_fwa_data(mongo)
    if fwa_data:
        return FWA(data=fwa_data)
    return None
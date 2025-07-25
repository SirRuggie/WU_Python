from utils.mongo import MongoClient
from utils.classes import FWA

async def get_fwa_base_object(mongo: MongoClient):
    fwa_data = await mongo.fwa_data.find().to_list(length=1)
    if fwa_data:
        return FWA(data=fwa_data[0])
    return None
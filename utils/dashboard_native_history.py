"""Journal native message editors through the dashboard's shared history format."""
async def save_message(writer,prefix,mongo,guild_id,key,*args):
    from cwl_web.manage_content import GUILD_ID, descriptor, load, schema
    from cwl_web.change_history import begin,finish,fields
    if int(guild_id)!=GUILD_ID:
        return await writer(mongo,guild_id,key,*args)
    item=descriptor(prefix+'--'+key)
    before=await load(mongo,item)
    token=await begin(mongo,'/api/cwl/manage/content/'+item['id'],{'user_id':str(args[-1])},fields(schema(item,before)),'discord_edit',before)
    result=await writer(mongo,guild_id,key,*args)
    if result is not False:
        after=await load(mongo,item)
        await finish(mongo,token,fields(schema(item,after)),after)
    return result

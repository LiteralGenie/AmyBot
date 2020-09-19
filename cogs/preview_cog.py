from discord.ext import commands
from classes import PartialCog, PartialCommand
from classes.errors import PermissionError, TemplatedError

from utils.scraper_utils import get_session, get_html
from utils.pprint_utils import get_pages
from utils.parse_utils import int_to_price
from utils.perm_utils import check_perms

import bs4, datetime, discord, utils, asyncio
import regex as re # fix for allowing "infinite lookbehinds"


# Generate previews for certain links
class PreviewCog(PartialCog, name="Preview"):
	_excl= r"(!)?[\S]*" # check for ! prefix
	_b1= r"(?<!<.*)" # check for NOT < prefix
	_b2= r"(?!.*>)" # check for NOT > suffix
	LINK_REGEX= dict(
		equip= [
			rf"{_b1}{_excl}hentaiverse\.org/equip/([A-Za-z\d]+)/([A-Za-z\d]+){_b2}", # http://hentaiverse.org/equip/123487856/579b582136
			rf"{_b1}{_excl}eid=([A-Za-z\d]+)&key=([A-Za-z\d]+){_b2}" # old style -- http://hentaiverse.org/pages/showequip.php?eid=123487856&key=579b582136
		],
		thread= [
			rf"{_b1}{_excl}[\S]*e-hentai.*showtopic=(\d+)(?!.*&(?:p|pid)=\d+){_b2}" # https://forums.e-hentai.org/index.php?showtopic=236519
		],
		comment= [
			rf"{_b1}{_excl}e-hentai.*showtopic=(\d+).*&(?:p|pid)=(\d+){_b2}" # https://forums.e-hentai.org/index.php?s=&showtopic=204369&view=findpost&p=4816189
		],
		bounty= [
			rf"{_b1}{_excl}e-hentai.*bid=(\d+){_b2}" # https://e-hentai.org/bounty.php?bid=21180
		]
	)

	def __init__(self, bot, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.bot= bot
		self.session= get_session()

	# Scan each message for a supported link
	@commands.Cog.listener()
	async def on_message(self, message):
		if message.author.bot:
			return

		ctx= await self.bot.get_context(message)
		ctx.__dict__['command']= self._preview
		ctx.__dict__['cog']= self

		try: check_perms(ctx)
		except PermissionError:	return

		await self.scan_equip(ctx)
		await self.scan_bounty(ctx)
		await self.scan_thread(ctx)
		await self.scan_comment(ctx)

	async def scan_equip(self, ctx):
		pass


	async def scan_thread(self, ctx):
		# inits
		CONFIG= utils.load_yaml(utils.PREVIEW_CONFIG)
		max_body_len= CONFIG['max_body_length']
		max_body_lines= CONFIG['max_body_lines']
		max_title_len= CONFIG['max_title_length']

		# scan for links
		for x in self.LINK_REGEX['thread']:
			match= re.search(x, ctx.message.content)
			if match: break
		else:
			return # no match

		# get matches
		has_excl, thread_id= match.groups()

		# keep if-block in case future behavior of ! prefix changes
		if has_excl:
			pass

		# get html
		thread_link= "https://forums.e-hentai.org/index.php?showtopic=" + thread_id
		html= await get_html(thread_link, session=self.session)

		# get title + description
		soup= bs4.BeautifulSoup(html, 'html.parser')
		title= soup.find(class_="maintitle").find("div").get_text()
		desc= ""

		split= title.split(",", maxsplit=1)
		if len(split) > 1:
			title= split[0]
			desc= split[1]

		# get everything else
		soup= bs4.BeautifulSoup(html, 'html.parser').find("table", cellspacing="1")
		dct= await self._parse_post(soup)

		# limit preview length
		body= self._clean_body(dct['text'], CONFIG=CONFIG)
		title= self._clean_title(title, CONFIG=CONFIG)

		# send preview
		render_params= dict(
			title=title,
			sub_title=desc,
			username=dct['username'],
			user_link=dct['user_link'],
			body=body,
			year=dct['year'], month= dct['month'], day=dct['day']
		)

		embed= discord.Embed(
			title= utils.render(CONFIG['thread_title_template'], render_params),
			description= utils.render(CONFIG['thread_body_template'], render_params),
			url=thread_link
		)
		embed.set_thumbnail(url=dct['thumbnail'])

		await ctx.send(embed=embed)


	async def scan_comment(self, ctx):
		# inits
		CONFIG= utils.load_yaml(utils.PREVIEW_CONFIG)
		max_body_len= CONFIG['max_body_length']
		max_body_lines= CONFIG['max_body_lines']
		max_title_len= CONFIG['max_title_length']

		# scan for links
		for x in self.LINK_REGEX['comment']:
			match= re.search(x, ctx.message.content)
			if match: break
		else:
			return # no match

		# get matches
		has_excl, thread_id, post_id= match.groups()

		# keep if-block in case future behavior of ! prefix changes
		if has_excl:
			pass

		# get html
		thread_link= "https://forums.e-hentai.org/index.php?showtopic=" + thread_id + "&view=findpost&p=" + post_id
		html= await get_html(thread_link, session=self.session)

		# get title + description
		soup= bs4.BeautifulSoup(html, 'html.parser')
		title= soup.find(class_="maintitle").find("div").get_text()
		desc= ""

		split= title.split(",", maxsplit=1)
		if len(split) > 1:
			title= split[0]
			desc= split[1]

		# get everything else
		soup= bs4.BeautifulSoup(html, 'html.parser').find(id=f"post-main-{post_id}").parent.parent
		dct= await self._parse_post(soup)

		# limit preview length
		body= self._clean_body(dct['text'], CONFIG=CONFIG)
		title= self._clean_title(title, CONFIG=CONFIG)

		# send preview
		render_params= dict(
			title=title,
			username=dct['username'],
			user_link=dct['user_link'],
			body=body,
			year=dct['year'], month= dct['month'], day=dct['day']
		)

		embed= discord.Embed(
			title= utils.render(CONFIG['thread_title_template'], render_params),
			description= utils.render(CONFIG['thread_body_template'], render_params),
			url=thread_link
		)
		embed.set_thumbnail(url=dct['thumbnail'])

		await ctx.send(embed=embed)

	async def scan_bounty(self, ctx):
		# inits
		CONFIG= utils.load_yaml(utils.PREVIEW_CONFIG)
		max_body_len= CONFIG['max_body_length']
		max_body_lines= CONFIG['max_body_lines']
		max_title_len= CONFIG['max_title_length']
		max_tries= CONFIG['max_tries']
		try_delay= 5

		# scan for links
		for x in self.LINK_REGEX['bounty']:
			match= re.search(x, ctx.message.content)
			if match: break
		else:
			return # no match

		# get matches
		has_excl, bounty_id= match.groups()

		# keep if-block in case future behavior of ! prefix changes
		if has_excl:
			pass

		# get html
		bounty_link= "https://e-hentai.org/bounty.php?bid=" + bounty_id
		html= await get_html(bounty_link, session=self.session)

		tries= 1
		fail_string= "This page requires you to log on."
		while fail_string in html and tries < max_tries:
			await asyncio.sleep(try_delay)
			self.session= await self._do_login(session=self.session)
			html= await get_html(bounty_link, self.session)
			tries+= 1
		if fail_string in html:
			print(f"Max retries exceeded for bounty: {bounty_link}")
			return

		# get info
		soup= bs4.BeautifulSoup(html, 'html.parser')

		title= soup.find(class_="stuffbox").find("h1").get_text()
		text= self._post_to_text(soup.find(id="x"))
		username= soup.find(class_="r").get_text()
		user_link= soup.find(class_="r").find("a")['href']
		thumbnail= await self._get_avatar_link(user_link)
		# thumbnail= soup.find("img")['src']

		date= soup.find_all(class_="r")[1].get_text().split()[0]
		year,month,day= [int(x) for x in date.split("-")]

		typ= soup.find_all(class_="r")[2].get_text()
		status= soup.find_all(class_="r")[3].get_text()

		# reward calculations
		tmp= soup.find_all(class_="r")[5].get_text()
		tmp= re.search(r"([\d,]+) Credits \+ ([\d,]+) Hath", tmp).groups()
		credits= int_to_price(tmp[0])
		hath= int_to_price(tmp[1])

		raw_credits= int(tmp[0].replace(",",""))
		raw_hath= int(tmp[1].replace(",",""))

		credit_val= raw_credits + raw_hath*CONFIG['hath_value']
		credit_val= int_to_price(credit_val)

		hath_val= raw_hath + raw_credits // CONFIG['hath_value']
		hath_val= int_to_price(hath_val)

		# limit preview length
		body= self._clean_body(text, CONFIG=CONFIG)
		title= self._clean_title(title, CONFIG=CONFIG)

		# send preview
		render_params= dict(
			title=title,
			username=username,
			user_link=user_link,
			body=body,
			credits=credits, credit_value=credit_val,
			hath=hath, hath_value=hath_val,
			year=year, month=month, day=day,
			type=typ,
			status=status
		)

		embed= discord.Embed(
			title= utils.render(CONFIG['bounty_title_template'], render_params),
			description= utils.render(CONFIG['bounty_body_template'], render_params),
			url=bounty_link
		)
		embed.set_thumbnail(url=thumbnail)

		await ctx.send(embed=embed)


	# elem.get_text() wont print correctly due to bbcode formatting
	# so apply various fixes before grabbing string to parse
	@classmethod
	def _post_to_text(cls, soup):
		# [y.replace_with(f"{y.get_text()}") for y in sct.find_all("b")] bold text
		[x.replace_with("\n") for x in soup.find_all("br")] # new lines

		return "\n".join(x for x in soup.get_text().split("\n") if x)

	@staticmethod
	def _get_datetime(time_string):
		MONTHS= "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

		split= time_string.strip().split(" ") # Jul 27 2020, 12:06   OR    Today, 12:58     OR     Yesterday, 23:17
		hr,min= split[-1].split(":") # 12:06

		date= datetime.datetime.today().replace(hour=int(hr),minute=int(min))
		if "Yesterday," in split[0]:
			date= date.replace(day=date.day-1)
		else:
			date= date.replace(year=int(split[2][:-1]), # remove comma
							   month=1+MONTHS.index(split[0]), # month string to 1-indexed int
							   day=int(split[1]))

		return date

	async def _parse_post(self, soup):
		# get text content
		post_text= self._post_to_text(soup.find(class_="postcolor"))

		# get date
		date= soup.find(lambda x: x.get("style") and "float: left;" in x.get("style") and x.name == "div")
		date= date.get_text().strip()
		date= self._get_datetime(date)
		# date= date.strftime("%Y-%m-%d")

		# get user info
		tmp= soup.find("span", class_="bigusername").find("a")
		username= tmp.get_text().strip()
		user_link= tmp['href']

		# get thumbnail link
		thumbnail= await self._get_avatar_link(user_link)

		return dict(
			text=post_text,
			thumbnail=thumbnail,
			username=username, user_link=user_link,
			year=date.year, month=date.month, day=date.day
		)

	async def _get_avatar_link(self, link):
		thumbnail= f"https://forums.e-hentai.org/uploads/av-{link.split('=')[-1]}"
		for x in ['.jpg', '.png']:
			try:
				await get_html(thumbnail+x, session=self.session)
				thumbnail+= x
				break
			except TemplatedError:
				continue
		else:
			thumbnail=""

		return thumbnail

	@staticmethod
	async def _do_login(session=None):
		CONFIG= utils.load_json_with_default(utils.BOT_CONFIG_FILE,default=False)
		if session is None:
			session= get_session()

		# from chrome's network tab
		headers = {
			'Connection': 'keep-alive',
			'Cache-Control': 'max-age=0',
			'Origin': 'https://e-hentai.org',
			'Upgrade-Insecure-Requests': '1',
			'DNT': '1',
			'Content-Type': 'application/x-www-form-urlencoded',
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36',
			'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
			'Sec-Fetch-Site': 'same-site',
			'Sec-Fetch-Mode': 'navigate',
			'Sec-Fetch-User': '?1',
			'Sec-Fetch-Dest': 'document',
			'Referer': 'https://e-hentai.org/',
			'Accept-Language': 'en-US,en;q=0.9',
		}

		params = (
			('act', 'Login'),
			('CODE', '01'),
		)

		data = {
		  'CookieDate': '1',
		  'b': 'd',
		  'bt': '1-5',
		  'UserName': CONFIG['eh_username'],
		  'PassWord': CONFIG['eh_password'],
		  'ipb_login_submit': 'Login!'
		}

		await session.post(r"https://forums.e-hentai.org/index.php", headers=headers, params=params, data=data)
		return session

	@staticmethod
	def _clean_title(title, CONFIG=None):
		if CONFIG is None:
			CONFIG= utils.load_yaml(utils.PREVIEW_CONFIG)

		if len(title) > title[:CONFIG['max_title_length']]:
			title= title[:CONFIG['max_title_length']-3] + "..."
		title= title.replace("\n"," ")
		return title

	@staticmethod
	def _clean_body(body, CONFIG=None):
		if CONFIG is None:
			CONFIG= utils.load_yaml(utils.PREVIEW_CONFIG)

		# limit preview length
		tmp= [x.strip() for x in body.split("\n")]
		pages= get_pages(tmp, max_len=CONFIG['max_body_length'], no_orphan=0, join_char="\n\n")
		body= pages[0]

		split= body.split("\n")
		body= "\n".join(split[:CONFIG['max_body_lines']])
		if len(pages) > 1 or len(split) > CONFIG['max_body_lines']:
			body+= "\n\n[...]"

		# clean up
		while "\n\n\n" in body:
			body= body.replace("\n\n\n","\n\n")

		return body

	# Just so there's an entry in the help command.
	@commands.command(name="preview", short="preview", cls=PartialCommand)
	async def _preview(self):
		pass

if __name__ == "__main__":
	async def go():
		headers = {
			'Connection': 'keep-alive',
			'Cache-Control': 'max-age=0',
			'Origin': 'https://e-hentai.org',
			'Upgrade-Insecure-Requests': '1',
			'DNT': '1',
			'Content-Type': 'application/x-www-form-urlencoded',
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36',
			'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
			'Sec-Fetch-Site': 'same-site',
			'Sec-Fetch-Mode': 'navigate',
			'Sec-Fetch-User': '?1',
			'Sec-Fetch-Dest': 'document',
			'Referer': 'https://e-hentai.org/',
			'Accept-Language': 'en-US,en;q=0.9',
		}

		params = (
			('act', 'Login'),
			('CODE', '01'),
		)

		data = {
		  'CookieDate': '1',
		  'b': 'd',
		  'bt': '1-5',
		  'UserName': 'Frotag',
		  'PassWord': 'a1s2d3f4',
		  'ipb_login_submit': 'Login!'
		}

		session= get_session()
		response= session.post('https://forums.e-hentai.org/index.php', headers=headers, params=params, data=data)
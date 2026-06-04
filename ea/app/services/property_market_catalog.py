from __future__ import annotations

from dataclasses import dataclass
import re
import urllib.parse


@dataclass(frozen=True)
class PropertyCountrySpec:
    code: str
    label: str
    default_language: str
    currency_code: str
    currency_symbol: str
    location_placeholder: str
    featured_platforms: tuple[str, ...]


@dataclass(frozen=True)
class PropertyProviderSpec:
    key: str
    label: str
    country_code: str
    host_markers: tuple[str, ...]
    listing_path_markers: tuple[str, ...]
    search_urls: dict[str, str]
    description: str
    supported_listing_modes: tuple[str, ...] = ("rent", "buy")


COUNTRIES: tuple[PropertyCountrySpec, ...] = (
    PropertyCountrySpec("AT", "Austria", "de", "EUR", "EUR", "Vienna, Graz, Linz", ("willhaben", "immmo", "immoscout_at", "kalandra")),
    PropertyCountrySpec("BE", "Belgium", "nl", "EUR", "EUR", "Brussels, Antwerp, Ghent", ("immoweb", "zimmo")),
    PropertyCountrySpec("CA", "Canada", "en", "CAD", "CAD", "Toronto, Montreal, Vancouver", ("realtor_ca", "rew_ca", "rentals_ca")),
    PropertyCountrySpec("DE", "Germany", "de", "EUR", "EUR", "Berlin, Munich, Hamburg", ("immoscout_de", "immowelt", "immonet", "kleinanzeigen_immo")),
    PropertyCountrySpec("CH", "Switzerland", "de", "CHF", "CHF", "Zurich, Geneva, Basel", ("homegate", "newhome", "immoscout_ch")),
    PropertyCountrySpec("IE", "Ireland", "en", "EUR", "EUR", "Dublin, Cork, Galway", ("daft_ie", "myhome_ie")),
    PropertyCountrySpec("UK", "United Kingdom", "en", "GBP", "GBP", "London, Manchester, Bristol", ("rightmove", "zoopla", "onthemarket")),
    PropertyCountrySpec("AU", "Australia", "en", "AUD", "AUD", "Sydney, Melbourne, Brisbane", ("realestate_au", "domain_au", "flatmates_au")),
    PropertyCountrySpec("ES", "Spain", "es", "EUR", "EUR", "Barcelona, Madrid, Valencia", ("idealista_es", "fotocasa", "habitaclia")),
    PropertyCountrySpec("IT", "Italy", "it", "EUR", "EUR", "Milan, Rome, Bologna", ("immobiliare", "idealista_it", "casa_it")),
    PropertyCountrySpec("FR", "France", "fr", "EUR", "EUR", "Paris, Lyon, Marseille", ("seloger", "bienici", "leboncoin_immo")),
    PropertyCountrySpec("NL", "Netherlands", "nl", "EUR", "EUR", "Amsterdam, Rotterdam, Utrecht", ("funda", "pararius")),
    PropertyCountrySpec("PT", "Portugal", "pt", "EUR", "EUR", "Lisbon, Porto, Faro", ("idealista_pt", "imovirtual", "casa_sapo")),
    PropertyCountrySpec("PL", "Poland", "pl", "PLN", "PLN", "Warsaw, Krakow, Wroclaw", ("otodom", "olx_pl_nieruchomosci")),
    PropertyCountrySpec("SE", "Sweden", "sv", "SEK", "SEK", "Stockholm, Gothenburg, Malmo", ("hemnet", "booli")),
    PropertyCountrySpec("US", "United States", "en", "USD", "USD", "Brooklyn, Austin, Seattle", ("zillow", "realtor", "apartments")),
)


LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("it", "Italiano"),
    ("nl", "Nederlands"),
    ("pt", "Português"),
    ("pl", "Polski"),
    ("sv", "Svenska"),
)


LISTING_MODE_LABELS = {
    "rent": "Rent",
    "buy": "Buy",
}


PROPERTY_TYPE_LABELS = {
    "any": "Any type",
    "apartment": "Apartment",
    "house": "House",
}


ALERT_FREQUENCY_LABELS = {
    "manual": "Manual only",
    "daily": "Daily",
    "weekday": "Weekdays",
    "instant": "Instant",
}


ALERT_CHANNEL_KEYS = ("telegram", "email")


PROVIDERS: tuple[PropertyProviderSpec, ...] = (
    PropertyProviderSpec(
        key="willhaben",
        label="Willhaben",
        country_code="AT",
        host_markers=("willhaben.at",),
        listing_path_markers=("/iad/immobilien/d/", "/iad/object"),
        search_urls={
            "rent": "https://www.willhaben.at/iad/immobilien/mietwohnungen",
            "buy": "https://www.willhaben.at/iad/immobilien/eigentumswohnung",
        },
        description="Austria broad-market marketplace with dense residential volume.",
    ),
    PropertyProviderSpec(
        key="immmo",
        label="immmo",
        country_code="AT",
        host_markers=("immmo.at",),
        listing_path_markers=("/expose/", "/immobilien/", "/detail/"),
        search_urls={
            "rent": "https://www.immmo.at/suche/miete",
            "buy": "https://www.immmo.at/suche/kauf",
        },
        description="Austria portal with residential search feeds and alert traffic.",
    ),
    PropertyProviderSpec(
        key="immoscout_at",
        label="ImmoScout24 Austria",
        country_code="AT",
        host_markers=("immoscout24.at", "immobilienscout24.at"),
        listing_path_markers=("/expose/", "/detail/", "/objekt/"),
        search_urls={
            "rent": "https://www.immoscout24.at/liste/miete",
            "buy": "https://www.immoscout24.at/liste/kauf",
        },
        description="Austria search portal for rentals and residential purchase.",
    ),
    PropertyProviderSpec(
        key="kalandra",
        label="Kalandra",
        country_code="AT",
        host_markers=("kalandra.at",),
        listing_path_markers=("/objekt/",),
        search_urls={
            "rent": "https://www.kalandra.at/objekte",
            "buy": "https://www.kalandra.at/objekte",
        },
        description="Austria brokerage inventory with high-value marketing packets.",
    ),
    PropertyProviderSpec(
        key="justiz_edikte_at",
        label="Justiz Edikte Auctions",
        country_code="AT",
        host_markers=("edikte.justiz.gv.at", "edikte2.justiz.gv.at"),
        listing_path_markers=("/edikte/ex/exedi3.nsf/", "/ex/exedi3.nsf/0/"),
        search_urls={
            "buy": "https://edikte2.justiz.gv.at/edikte/ex/exedi3.nsf/Suche!OpenForm",
        },
        description="Austria judicial foreclosure and forced-sale publications from the Ediktsdatei.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="immoweb",
        label="Immoweb",
        country_code="BE",
        host_markers=("immoweb.be",),
        listing_path_markers=("/en/classified/", "/nl/zoekertje/", "/fr/annonce/"),
        search_urls={
            "rent": "https://www.immoweb.be/en/search/apartment-and-house/for-rent",
            "buy": "https://www.immoweb.be/en/search/apartment-and-house/for-sale",
        },
        description="Belgium flagship property portal with dense urban inventory.",
    ),
    PropertyProviderSpec(
        key="zimmo",
        label="Zimmo",
        country_code="BE",
        host_markers=("zimmo.be",),
        listing_path_markers=("/en/", "/nl/", "/fr/"),
        search_urls={
            "rent": "https://www.zimmo.be/en/search/for-rent/",
            "buy": "https://www.zimmo.be/en/search/for-sale/",
        },
        description="Belgium residential marketplace with strong Flemish supply.",
    ),
    PropertyProviderSpec(
        key="biddit_be",
        label="Biddit",
        country_code="BE",
        host_markers=("biddit.be",),
        listing_path_markers=("/fr/catalogue/", "/nl/catalogus/", "/en/catalog/", "/detail/"),
        search_urls={
            "buy": "https://www.biddit.be",
        },
        description="Belgium public property auction platform of the Royal Federation of Belgian Notaries.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="taxsales_ca",
        label="TaxSalesPortal",
        country_code="CA",
        host_markers=("taxsalesportal.ca",),
        listing_path_markers=("/property/", "/foreclosed-properties/", "/tax-sale-property/"),
        search_urls={
            "buy": "https://taxsalesportal.ca/foreclosed-properties/",
        },
        description="Canada distressed property and tax-sale aggregation across provincial auction processes.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="immoscout_de",
        label="ImmoScout24 Germany",
        country_code="DE",
        host_markers=("immobilienscout24.de", "immoscout24.de"),
        listing_path_markers=("/expose/", "/expose", "/detail/"),
        search_urls={
            "rent": "https://www.immobilienscout24.de/Suche/de/wohnung-mieten",
            "buy": "https://www.immobilienscout24.de/Suche/de/wohnung-kaufen",
        },
        description="Germany flagship portal for rental and purchase search.",
    ),
    PropertyProviderSpec(
        key="immowelt",
        label="Immowelt",
        country_code="DE",
        host_markers=("immowelt.de",),
        listing_path_markers=("/expose/", "/immobilien/"),
        search_urls={
            "rent": "https://www.immowelt.de/suche/mietwohnungen",
            "buy": "https://www.immowelt.de/suche/kaufen/wohnung",
        },
        description="Germany portal with broad inventory and structured listing pages.",
    ),
    PropertyProviderSpec(
        key="immonet",
        label="Immonet",
        country_code="DE",
        host_markers=("immonet.de",),
        listing_path_markers=("/expose/", "/angebot/"),
        search_urls={
            "rent": "https://www.immonet.de/wohnung-mieten.html",
            "buy": "https://www.immonet.de/wohnung-kaufen.html",
        },
        description="Germany search inventory with apartment rent and buy lanes.",
    ),
    PropertyProviderSpec(
        key="kleinanzeigen_immo",
        label="Kleinanzeigen Immobilien",
        country_code="DE",
        host_markers=("kleinanzeigen.de",),
        listing_path_markers=("/s-anzeige/",),
        search_urls={
            "rent": "https://www.kleinanzeigen.de/s-wohnung-mieten/c203",
            "buy": "https://www.kleinanzeigen.de/s-wohnung-kaufen/c196",
        },
        description="Germany classifieds lane that still surfaces off-market-style inventory.",
    ),
    PropertyProviderSpec(
        key="zvg_de",
        label="ZVG Portal",
        country_code="DE",
        host_markers=("zvg-portal.de",),
        listing_path_markers=("button=showzvg", "button=show", "/index.php?button=show"),
        search_urls={
            "buy": "https://www.zvg-portal.de/",
        },
        description="Germany official court publication portal for real-estate foreclosure auction dates.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="homegate",
        label="Homegate",
        country_code="CH",
        host_markers=("homegate.ch",),
        listing_path_markers=("/rent/", "/buy/"),
        search_urls={
            "rent": "https://www.homegate.ch/rent/real-estate/country-switzerland",
            "buy": "https://www.homegate.ch/buy/real-estate/country-switzerland",
        },
        description="Switzerland mainstream residential portal.",
    ),
    PropertyProviderSpec(
        key="newhome",
        label="newhome",
        country_code="CH",
        host_markers=("newhome.ch",),
        listing_path_markers=("/de/", "/fr/", "/it/"),
        search_urls={
            "rent": "https://www.newhome.ch/de/mieten/immobilien",
            "buy": "https://www.newhome.ch/de/kaufen/immobilien",
        },
        description="Switzerland portal with canton-heavy residential coverage.",
    ),
    PropertyProviderSpec(
        key="immoscout_ch",
        label="ImmoScout24 Switzerland",
        country_code="CH",
        host_markers=("immoscout24.ch",),
        listing_path_markers=("/rent/", "/buy/", "/en/"),
        search_urls={
            "rent": "https://www.immoscout24.ch/en/real-estate/rent",
            "buy": "https://www.immoscout24.ch/en/real-estate/buy",
        },
        description="Switzerland ImmoScout variant for multilingual search.",
    ),
    PropertyProviderSpec(
        key="auctionhome_ch",
        label="AuctionHome",
        country_code="CH",
        host_markers=("auctionhome.ch",),
        listing_path_markers=("/objekt/", "/property/", "/auction/"),
        search_urls={
            "buy": "https://www.en.auctionhome.ch/",
        },
        description="Switzerland property foreclosure auction listings sourced from debt collection and bankruptcy offices.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="daft_ie",
        label="Daft.ie",
        country_code="IE",
        host_markers=("daft.ie",),
        listing_path_markers=("/for-rent/", "/for-sale/"),
        search_urls={
            "rent": "https://www.daft.ie/property-for-rent/ireland",
            "buy": "https://www.daft.ie/property-for-sale/ireland",
        },
        description="Ireland flagship residential portal.",
    ),
    PropertyProviderSpec(
        key="myhome_ie",
        label="MyHome.ie",
        country_code="IE",
        host_markers=("myhome.ie",),
        listing_path_markers=("/residential/",),
        search_urls={
            "rent": "https://www.myhome.ie/rentals",
            "buy": "https://www.myhome.ie/residential",
        },
        description="Ireland portal with agency-led sale and rental inventory.",
    ),
    PropertyProviderSpec(
        key="youbid_ie",
        label="Youbid",
        country_code="IE",
        host_markers=("youbid.ie",),
        listing_path_markers=("/property/", "/details/", "/auction/"),
        search_urls={
            "buy": "https://www.youbid.ie/",
        },
        description="Ireland national online property auction platform used for distressed and receiver-led sales.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="rightmove",
        label="Rightmove",
        country_code="UK",
        host_markers=("rightmove.co.uk",),
        listing_path_markers=("/properties/",),
        search_urls={
            "rent": "https://www.rightmove.co.uk/property-to-rent.html",
            "buy": "https://www.rightmove.co.uk/property-for-sale.html",
        },
        description="United Kingdom flagship property portal.",
    ),
    PropertyProviderSpec(
        key="zoopla",
        label="Zoopla",
        country_code="UK",
        host_markers=("zoopla.co.uk",),
        listing_path_markers=("/to-rent/details/", "/for-sale/details/"),
        search_urls={
            "rent": "https://www.zoopla.co.uk/to-rent/property/",
            "buy": "https://www.zoopla.co.uk/for-sale/property/",
        },
        description="United Kingdom portal with broad consumer search share.",
    ),
    PropertyProviderSpec(
        key="onthemarket",
        label="OnTheMarket",
        country_code="UK",
        host_markers=("onthemarket.com",),
        listing_path_markers=("/details/",),
        search_urls={
            "rent": "https://www.onthemarket.com/to-rent/",
            "buy": "https://www.onthemarket.com/for-sale/",
        },
        description="United Kingdom portal with agency inventory and structured detail pages.",
    ),
    PropertyProviderSpec(
        key="repolist_uk",
        label="Repolist",
        country_code="UK",
        host_markers=("repolist.co.uk",),
        listing_path_markers=("/property/", "/auction/", "/listing/"),
        search_urls={
            "buy": "https://repolist.co.uk/",
        },
        description="United Kingdom repossessed-property and auction discovery portal.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="realestate_au",
        label="realestate.com.au",
        country_code="AU",
        host_markers=("realestate.com.au",),
        listing_path_markers=("/property-", "/project/"),
        search_urls={
            "rent": "https://www.realestate.com.au/rent",
            "buy": "https://www.realestate.com.au/buy",
        },
        description="Australia flagship portal for rent and buy search.",
    ),
    PropertyProviderSpec(
        key="domain_au",
        label="Domain",
        country_code="AU",
        host_markers=("domain.com.au",),
        listing_path_markers=("/address-",),
        search_urls={
            "rent": "https://www.domain.com.au/rent/",
            "buy": "https://www.domain.com.au/sale/",
        },
        description="Australia national property portal with structured listing pages.",
    ),
    PropertyProviderSpec(
        key="flatmates_au",
        label="Flatmates",
        country_code="AU",
        host_markers=("flatmates.com.au",),
        listing_path_markers=("/share-house/", "/people/"),
        search_urls={
            "rent": "https://flatmates.com.au/rooms",
            "buy": "https://flatmates.com.au/rooms",
        },
        description="Australia shared-living and room-rental marketplace.",
        supported_listing_modes=("rent",),
    ),
    PropertyProviderSpec(
        key="mortgagee_au",
        label="Mortgagee Sales Australia",
        country_code="AU",
        host_markers=("ozhousehunters.com.au", "lloydsonline.com.au"),
        listing_path_markers=("/mortgagee", "/property/", "/AuctionDetails.aspx"),
        search_urls={
            "buy": "https://www.ozhousehunters.com.au/",
        },
        description="Australia mortgagee-in-possession and distressed property sales feed.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="idealista_es",
        label="Idealista Spain",
        country_code="ES",
        host_markers=("idealista.com",),
        listing_path_markers=("/inmueble/",),
        search_urls={
            "rent": "https://www.idealista.com/en/alquiler-viviendas/",
            "buy": "https://www.idealista.com/en/venta-viviendas/",
        },
        description="Spain flagship portal for residential discovery.",
    ),
    PropertyProviderSpec(
        key="fotocasa",
        label="Fotocasa",
        country_code="ES",
        host_markers=("fotocasa.es",),
        listing_path_markers=("/es/", "/vivienda/"),
        search_urls={
            "rent": "https://www.fotocasa.es/es/alquiler/viviendas/espana/todas-las-zonas/l",
            "buy": "https://www.fotocasa.es/es/comprar/viviendas/espana/todas-las-zonas/l",
        },
        description="Spain residential search portal.",
    ),
    PropertyProviderSpec(
        key="habitaclia",
        label="Habitaclia",
        country_code="ES",
        host_markers=("habitaclia.com",),
        listing_path_markers=("/comprar-", "/alquiler-"),
        search_urls={
            "rent": "https://www.habitaclia.com/alquiler.htm",
            "buy": "https://www.habitaclia.com/comprar.htm",
        },
        description="Spain portal with stronger Catalonia inventory but useful broader feeds.",
    ),
    PropertyProviderSpec(
        key="boe_subastas_es",
        label="BOE Subastas",
        country_code="ES",
        host_markers=("subastas.boe.es", "sedejudicial.justicia.es"),
        listing_path_markers=("/subastas/", "idSub=", "/buscar.php"),
        search_urls={
            "buy": "https://subastas.boe.es/subastas_ava.php?campo%5B0%5D=SUBASTA.INMUEBLES",
        },
        description="Spain official electronic judicial and administrative auction portal for real estate.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="immobiliare",
        label="Immobiliare.it",
        country_code="IT",
        host_markers=("immobiliare.it",),
        listing_path_markers=("/annunci/",),
        search_urls={
            "rent": "https://www.immobiliare.it/affitto-case/",
            "buy": "https://www.immobiliare.it/vendita-case/",
        },
        description="Italy flagship residential marketplace.",
    ),
    PropertyProviderSpec(
        key="idealista_it",
        label="Idealista Italy",
        country_code="IT",
        host_markers=("idealista.it",),
        listing_path_markers=("/immobile/",),
        search_urls={
            "rent": "https://www.idealista.it/affitto-case/",
            "buy": "https://www.idealista.it/vendita-case/",
        },
        description="Italy branch of Idealista with broad urban inventory.",
    ),
    PropertyProviderSpec(
        key="casa_it",
        label="Casa.it",
        country_code="IT",
        host_markers=("casa.it",),
        listing_path_markers=("/immobili/",),
        search_urls={
            "rent": "https://www.casa.it/affitto/residenziale/",
            "buy": "https://www.casa.it/vendita/residenziale/",
        },
        description="Italy residential search portal.",
    ),
    PropertyProviderSpec(
        key="aste_giudiziarie_it",
        label="Aste Giudiziarie",
        country_code="IT",
        host_markers=("astegiudiziarie.it",),
        listing_path_markers=("/vendita/", "/asta-giudiziaria/", "/immobili/"),
        search_urls={
            "buy": "https://www.astegiudiziarie.it/",
        },
        description="Italy judicial real-estate auction portal centered on court-published asset sales.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="seloger",
        label="SeLoger",
        country_code="FR",
        host_markers=("seloger.com",),
        listing_path_markers=("/annonces/",),
        search_urls={
            "rent": "https://www.seloger.com/list.htm?projects=1&types=1",
            "buy": "https://www.seloger.com/list.htm?projects=2&types=1",
        },
        description="France flagship portal with structured listing pages.",
    ),
    PropertyProviderSpec(
        key="bienici",
        label="Bien'ici",
        country_code="FR",
        host_markers=("bienici.com",),
        listing_path_markers=("/annonce/",),
        search_urls={
            "rent": "https://www.bienici.com/recherche/location/france",
            "buy": "https://www.bienici.com/recherche/achat/france",
        },
        description="France map-heavy search portal.",
    ),
    PropertyProviderSpec(
        key="leboncoin_immo",
        label="Leboncoin Immobilier",
        country_code="FR",
        host_markers=("leboncoin.fr",),
        listing_path_markers=("/ad/",),
        search_urls={
            "rent": "https://www.leboncoin.fr/recherche?category=10&real_estate_type=2",
            "buy": "https://www.leboncoin.fr/recherche?category=9&real_estate_type=1",
        },
        description="France classifieds lane with residential supply.",
    ),
    PropertyProviderSpec(
        key="avoventes_fr",
        label="Avoventes",
        country_code="FR",
        host_markers=("avoventes.fr",),
        listing_path_markers=("/annonce/", "/vente-judiciaire/", "/encheres/"),
        search_urls={
            "buy": "https://avoventes.fr/",
        },
        description="France national public auction announcement platform for judicial real-estate sales.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="funda",
        label="Funda",
        country_code="NL",
        host_markers=("funda.nl",),
        listing_path_markers=("/detail/",),
        search_urls={
            "rent": "https://www.funda.nl/zoeken/huur/",
            "buy": "https://www.funda.nl/zoeken/koop/",
        },
        description="Netherlands flagship portal.",
    ),
    PropertyProviderSpec(
        key="pararius",
        label="Pararius",
        country_code="NL",
        host_markers=("pararius.com", "pararius.nl"),
        listing_path_markers=("/apartment-for-rent/", "/huis-te-huur/"),
        search_urls={
            "rent": "https://www.pararius.com/apartments",
            "buy": "https://www.pararius.com/houses-for-sale",
        },
        description="Netherlands rental-heavy portal.",
    ),
    PropertyProviderSpec(
        key="veilingdeurwaarder_nl",
        label="Veilingdeurwaarder",
        country_code="NL",
        host_markers=("veilingdeurwaarder.nl",),
        listing_path_markers=("/veiling/", "/executieveiling/", "/kavel/"),
        search_urls={
            "buy": "https://www.veilingdeurwaarder.nl/zoeken/",
        },
        description="Netherlands public sale and executieveiling portal tied to judicial officers.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="idealista_pt",
        label="Idealista Portugal",
        country_code="PT",
        host_markers=("idealista.pt",),
        listing_path_markers=("/imovel/",),
        search_urls={
            "rent": "https://www.idealista.pt/en/arrendar-casas/",
            "buy": "https://www.idealista.pt/en/comprar-casas/",
        },
        description="Portugal branch of Idealista with strong Lisbon and Porto coverage.",
    ),
    PropertyProviderSpec(
        key="imovirtual",
        label="Imovirtual",
        country_code="PT",
        host_markers=("imovirtual.com",),
        listing_path_markers=("/imovel/",),
        search_urls={
            "rent": "https://www.imovirtual.com/arrendar/apartamento/",
            "buy": "https://www.imovirtual.com/comprar/apartamento/",
        },
        description="Portugal residential search portal with broad rental coverage.",
    ),
    PropertyProviderSpec(
        key="casa_sapo",
        label="Casa Sapo",
        country_code="PT",
        host_markers=("casa.sapo.pt",),
        listing_path_markers=("/detalhes/",),
        search_urls={
            "rent": "https://casa.sapo.pt/en-gb/rent-apartments/",
            "buy": "https://casa.sapo.pt/en-gb/buy-apartments/",
        },
        description="Portugal property portal with agency inventory.",
    ),
    PropertyProviderSpec(
        key="citius_exec_pt",
        label="Citius Judicial Sales",
        country_code="PT",
        host_markers=("citius.mj.pt", "portaldasfinancas.gov.pt"),
        listing_path_markers=("/consultasvenda.aspx", "/bens/", "/venda/"),
        search_urls={
            "buy": "https://www.citius.mj.pt/portal/consultas/consultasvenda.aspx/1000",
        },
        description="Portugal public portal for judicial and tax-enforcement sales of seized property.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="otodom",
        label="Otodom",
        country_code="PL",
        host_markers=("otodom.pl",),
        listing_path_markers=("/pl/oferta/",),
        search_urls={
            "rent": "https://www.otodom.pl/pl/wyniki/wynajem/mieszkanie/cala-polska",
            "buy": "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/cala-polska",
        },
        description="Poland flagship property portal.",
    ),
    PropertyProviderSpec(
        key="olx_pl_nieruchomosci",
        label="OLX Nieruchomości",
        country_code="PL",
        host_markers=("olx.pl",),
        listing_path_markers=("/d/oferta/",),
        search_urls={
            "rent": "https://www.olx.pl/nieruchomosci/mieszkania/wynajem/",
            "buy": "https://www.olx.pl/nieruchomosci/mieszkania/sprzedaz/",
        },
        description="Poland classifieds lane for residential supply.",
    ),
    PropertyProviderSpec(
        key="komornik_elicytacje_pl",
        label="Komornik e-Licytacje",
        country_code="PL",
        host_markers=("elicytacje.komornik.pl", "ool.komornik.pl"),
        listing_path_markers=("/licytacje/", "/items/", "/obwieszczenia/"),
        search_urls={
            "buy": "https://elicytacje.komornik.pl/",
        },
        description="Poland official bailiff auction portal for court-enforced real-estate sales.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="hemnet",
        label="Hemnet",
        country_code="SE",
        host_markers=("hemnet.se",),
        listing_path_markers=("/bostad/",),
        search_urls={
            "rent": "https://www.hemnet.se/bostader",
            "buy": "https://www.hemnet.se/bostader",
        },
        description="Sweden flagship property portal focused on sale inventory.",
    ),
    PropertyProviderSpec(
        key="booli",
        label="Booli",
        country_code="SE",
        host_markers=("booli.se",),
        listing_path_markers=("/bostad/",),
        search_urls={
            "rent": "https://www.booli.se/sok/bostad",
            "buy": "https://www.booli.se/sok/till-salu",
        },
        description="Sweden marketplace and valuation surface for home search.",
    ),
    PropertyProviderSpec(
        key="kronofogden_auktionstorget_se",
        label="Kronofogden Auktionstorget",
        country_code="SE",
        host_markers=("auktionstorget.kronofogden.se",),
        listing_path_markers=(".html",),
        search_urls={
            "buy": "https://auktionstorget.kronofogden.se/auktionstorget",
        },
        description="Sweden Enforcement Authority auction market for seized real estate and housing rights.",
        supported_listing_modes=("buy",),
    ),
    PropertyProviderSpec(
        key="zillow",
        label="Zillow",
        country_code="US",
        host_markers=("zillow.com",),
        listing_path_markers=("/_zpid/",),
        search_urls={
            "rent": "https://www.zillow.com/homes/for_rent/",
            "buy": "https://www.zillow.com/homes/for_sale/",
        },
        description="United States large-scale residential search portal.",
    ),
    PropertyProviderSpec(
        key="realtor",
        label="Realtor.com",
        country_code="US",
        host_markers=("realtor.com",),
        listing_path_markers=("/realestateandhomes-detail/",),
        search_urls={
            "rent": "https://www.realtor.com/apartments",
            "buy": "https://www.realtor.com/realestateandhomes-search",
        },
        description="United States residential marketplace with structured detail pages.",
    ),
    PropertyProviderSpec(
        key="apartments",
        label="Apartments.com",
        country_code="US",
        host_markers=("apartments.com",),
        listing_path_markers=("/apartments/", "/house/", "/condo/"),
        search_urls={
            "rent": "https://www.apartments.com/",
            "buy": "https://www.apartments.com/",
        },
        description="United States rental-heavy apartment portal.",
        supported_listing_modes=("rent",),
    ),
    PropertyProviderSpec(
        key="realtor_ca",
        label="Realtor.ca",
        country_code="CA",
        host_markers=("realtor.ca",),
        listing_path_markers=("/real-estate/",),
        search_urls={
            "rent": "https://www.realtor.ca/on/rent",
            "buy": "https://www.realtor.ca/",
        },
        description="Canada national residential portal.",
    ),
    PropertyProviderSpec(
        key="rew_ca",
        label="REW",
        country_code="CA",
        host_markers=("rew.ca",),
        listing_path_markers=("/properties/",),
        search_urls={
            "rent": "https://www.rew.ca/rentals",
            "buy": "https://www.rew.ca/properties",
        },
        description="Canada residential search portal with stronger western market coverage.",
    ),
    PropertyProviderSpec(
        key="rentals_ca",
        label="Rentals.ca",
        country_code="CA",
        host_markers=("rentals.ca",),
        listing_path_markers=("/city/", "/property/"),
        search_urls={
            "rent": "https://rentals.ca/",
            "buy": "https://rentals.ca/",
        },
        description="Canada rental-focused apartment portal.",
        supported_listing_modes=("rent",),
    ),
    PropertyProviderSpec(
        key="treasury_real_property_us",
        label="Treasury Real Property Auctions",
        country_code="US",
        host_markers=("treasury.gov",),
        listing_path_markers=("/auctions/treasury/rp/",),
        search_urls={
            "buy": "https://www.treasury.gov/auctions/treasury/rp/index.shtml",
        },
        description="United States federal seized-real-property auction listings open to the public.",
        supported_listing_modes=("buy",),
    ),
)


_COUNTRY_INDEX = {row.code: row for row in COUNTRIES}
_PROVIDER_INDEX = {row.key: row for row in PROVIDERS}
_LANGUAGE_INDEX = {code: label for code, label in LANGUAGES}


PROPERTY_PLATFORM_ALIAS_MAP: dict[str, str] = {
    "willhaben": "willhaben",
    "immmo": "immmo",
    "kalandra": "kalandra",
    "immoscout": "immoscout_at",
    "immoscout24": "immoscout_at",
    "immoscoutat": "immoscout_at",
    "justizedikte": "justiz_edikte_at",
    "edikte": "justiz_edikte_at",
    "immobilienscout": "immoscout_de",
    "immobilienscout24": "immoscout_de",
    "immobilienscout24de": "immoscout_de",
    "immoscoutde": "immoscout_de",
    "immoscoutch": "immoscout_ch",
    "immowelt": "immowelt",
    "immonet": "immonet",
    "kleinanzeigen": "kleinanzeigen_immo",
    "kleinanzeigenimmo": "kleinanzeigen_immo",
    "homegate": "homegate",
    "newhome": "newhome",
    "immoweb": "immoweb",
    "zimmo": "zimmo",
    "biddit": "biddit_be",
    "taxsalesportal": "taxsales_ca",
    "daft": "daft_ie",
    "daftie": "daft_ie",
    "myhome": "myhome_ie",
    "myhomeie": "myhome_ie",
    "youbid": "youbid_ie",
    "rightmove": "rightmove",
    "zoopla": "zoopla",
    "onthemarket": "onthemarket",
    "repolist": "repolist_uk",
    "realestateau": "realestate_au",
    "realestatecomau": "realestate_au",
    "domain": "domain_au",
    "flatmates": "flatmates_au",
    "mortgageeau": "mortgagee_au",
    "idealista": "idealista_es",
    "idealistaes": "idealista_es",
    "idealistait": "idealista_it",
    "idealistapt": "idealista_pt",
    "fotocasa": "fotocasa",
    "habitaclia": "habitaclia",
    "boesubastas": "boe_subastas_es",
    "immobiliare": "immobiliare",
    "astegiudiziarie": "aste_giudiziarie_it",
    "casait": "casa_it",
    "casa": "casa_it",
    "seloger": "seloger",
    "bienici": "bienici",
    "leboncoin": "leboncoin_immo",
    "leboncoinimmo": "leboncoin_immo",
    "avoventes": "avoventes_fr",
    "funda": "funda",
    "pararius": "pararius",
    "veilingdeurwaarder": "veilingdeurwaarder_nl",
    "imovirtual": "imovirtual",
    "casasapo": "casa_sapo",
    "citiusexec": "citius_exec_pt",
    "otodom": "otodom",
    "olxpl": "olx_pl_nieruchomosci",
    "olxnieruchomosci": "olx_pl_nieruchomosci",
    "komornik": "komornik_elicytacje_pl",
    "hemnet": "hemnet",
    "booli": "booli",
    "kronofogden": "kronofogden_auktionstorget_se",
    "zillow": "zillow",
    "realtor": "realtor",
    "apartments": "apartments",
    "realtorca": "realtor_ca",
    "rew": "rew_ca",
    "rentalsca": "rentals_ca",
    "treasuryrealproperty": "treasury_real_property_us",
    "zvg": "zvg_de",
    "auctionhome": "auctionhome_ch",
    "all": "all",
}


def normalize_property_platform(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw in _PROVIDER_INDEX or raw == "all":
        return raw
    normalized = re.sub(r"[^a-z0-9]+", "", raw)
    if not normalized:
        return ""
    if normalized in _PROVIDER_INDEX or normalized == "all":
        return normalized
    return PROPERTY_PLATFORM_ALIAS_MAP.get(normalized, normalized)


def property_platform_keys() -> tuple[str, ...]:
    return tuple(provider.key for provider in PROVIDERS)


def is_known_property_platform(value: object) -> bool:
    return normalize_property_platform(value) in _PROVIDER_INDEX


def normalize_country_code(value: object, *, default: str = "AT") -> str:
    code = str(value or "").strip().upper()
    return code if code in _COUNTRY_INDEX else default


def normalize_language_code(value: object, *, country_code: str = "AT") -> str:
    code = str(value or "").strip().lower()
    if code in _LANGUAGE_INDEX:
        return code
    return _COUNTRY_INDEX.get(normalize_country_code(country_code), _COUNTRY_INDEX["AT"]).default_language


def normalize_listing_mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"rent", "buy"} else "rent"


def normalize_property_type(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in PROPERTY_TYPE_LABELS else "any"


def country_options() -> list[dict[str, str]]:
    return [{"value": row.code, "label": row.label} for row in COUNTRIES]


def language_options() -> list[dict[str, str]]:
    return [{"value": code, "label": label} for code, label in LANGUAGES]


def listing_mode_options() -> list[dict[str, str]]:
    return [{"value": key, "label": label} for key, label in LISTING_MODE_LABELS.items()]


def property_type_options() -> list[dict[str, str]]:
    return [{"value": key, "label": label} for key, label in PROPERTY_TYPE_LABELS.items()]


def provider_options(*, country_code: str | None = None) -> list[dict[str, str]]:
    normalized_country = normalize_country_code(country_code, default="AT") if country_code else ""
    rows: list[dict[str, str]] = []
    for provider in PROVIDERS:
        if normalized_country and provider.country_code != normalized_country:
            continue
        country_label = _COUNTRY_INDEX.get(provider.country_code).label if provider.country_code in _COUNTRY_INDEX else provider.country_code
        rows.append(
            {
                "value": provider.key,
                "label": provider.label,
                "description": f"{country_label} | {provider.description}",
            }
        )
    return rows


def default_platforms_for_country(country_code: object) -> tuple[str, ...]:
    country = _COUNTRY_INDEX.get(normalize_country_code(country_code))
    return tuple(country.featured_platforms if country is not None else _COUNTRY_INDEX["AT"].featured_platforms)


def default_language_for_country(country_code: object) -> str:
    return _COUNTRY_INDEX.get(normalize_country_code(country_code), _COUNTRY_INDEX["AT"]).default_language


def country_label(country_code: object) -> str:
    return _COUNTRY_INDEX.get(normalize_country_code(country_code), _COUNTRY_INDEX["AT"]).label


def language_label(language_code: object, *, country_code: object = "AT") -> str:
    normalized = normalize_language_code(language_code, country_code=normalize_country_code(country_code))
    return _LANGUAGE_INDEX.get(normalized, _LANGUAGE_INDEX["en"])


def listing_mode_label(listing_mode: object) -> str:
    return LISTING_MODE_LABELS.get(normalize_listing_mode(listing_mode), LISTING_MODE_LABELS["rent"])


def property_type_label(property_type: object) -> str:
    return PROPERTY_TYPE_LABELS.get(normalize_property_type(property_type), PROPERTY_TYPE_LABELS["any"])


def provider_host_markers() -> tuple[str, ...]:
    return tuple(dict.fromkeys(marker for provider in PROVIDERS for marker in provider.host_markers))


def provider_listing_markers_for_host(hostname: object) -> tuple[str, ...]:
    host = str(hostname or "").strip().lower()
    markers: list[str] = []
    for provider in PROVIDERS:
        if any(marker in host for marker in provider.host_markers):
            markers.extend(provider.listing_path_markers)
    return tuple(dict.fromkeys(markers))


def property_provider_for_platform(platform_key: object) -> PropertyProviderSpec | None:
    return _PROVIDER_INDEX.get(normalize_property_platform(platform_key))


def normalize_property_search_preferences(preferences: dict[str, object] | None) -> dict[str, object]:
    payload = dict(preferences or {})
    country_code = normalize_country_code(payload.get("country_code"))
    payload["country_code"] = country_code
    payload["region_code"] = str(payload.get("region_code") or "").strip().lower()
    payload["language_code"] = normalize_language_code(payload.get("language_code"), country_code=country_code)
    payload["listing_mode"] = normalize_listing_mode(payload.get("listing_mode"))
    payload["property_type"] = normalize_property_type(payload.get("property_type"))
    payload["location_query"] = str(payload.get("location_query") or "").strip()
    payload["keywords"] = str(payload.get("keywords") or "").strip()
    normalized_alert_frequency = str(payload.get("alert_frequency") or "").strip().lower() or "daily"
    if normalized_alert_frequency not in ALERT_FREQUENCY_LABELS:
        normalized_alert_frequency = "daily"
    payload["alert_frequency"] = normalized_alert_frequency
    raw_alert_channels = payload.get("alert_channels")
    if isinstance(raw_alert_channels, (list, tuple, set)):
        alert_channels = [
            current
            for current in dict.fromkeys(str(item or "").strip().lower() for item in raw_alert_channels)
            if current in ALERT_CHANNEL_KEYS
        ]
    else:
        single_channel = str(raw_alert_channels or "").strip().lower()
        alert_channels = [single_channel] if single_channel in ALERT_CHANNEL_KEYS else []
    payload["alert_channels"] = alert_channels or ["telegram"]
    payload["selected_platforms"] = [
        current
        for current in dict.fromkeys(
            normalize_property_platform(item)
            for item in (payload.get("selected_platforms") or [])
            if normalize_property_platform(item) and normalize_property_platform(item) != "all"
        )
        if current in _PROVIDER_INDEX
    ]
    for numeric_key in ("min_price_eur", "max_price_eur", "min_rooms", "min_area_m2"):
        try:
            numeric_value = int(float(str(payload.get(numeric_key) or "").strip()))
        except Exception:
            numeric_value = 0
        if numeric_value > 0:
            payload[numeric_key] = numeric_value
        else:
            payload.pop(numeric_key, None)
    return payload


def _append_query(url: str, query_items: dict[str, str]) -> str:
    if not query_items:
        return url
    parsed = urllib.parse.urlparse(url)
    existing = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    for key, value in query_items.items():
        normalized = str(value or "").strip()
        if normalized:
            existing[key] = [normalized]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(existing, doseq=True)))


def _slug_tokens(value: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return [token for token in cleaned.split("-") if token]


def _location_slug(value: str) -> str:
    return "-".join(_slug_tokens(value))


def _location_query_variants(value: str) -> tuple[str, ...]:
    raw_parts = [str(part or "").strip() for part in str(value or "").split(",")]
    variants = tuple(part for part in raw_parts if part)
    return variants or (str(value or "").strip(),)


def _provider_property_type_segment(property_type: str) -> str:
    normalized = normalize_property_type(property_type)
    if normalized == "apartment":
        return "apartment"
    if normalized == "house":
        return "house"
    return ""


def _build_provider_search_url(
    *,
    provider: PropertyProviderSpec,
    base_url: str,
    listing_mode: str,
    location_query: str,
    keywords: str,
    property_type: str,
    max_price_eur: int | None,
    min_rooms: int | None,
) -> str:
    search_terms = " ".join(part for part in (location_query, keywords) if part).strip()
    location_slug = _location_slug(location_query)
    if provider.key == "immoscout_de" and location_slug:
        suffix = "wohnung-kaufen" if listing_mode == "buy" else "wohnung-mieten"
        return f"https://www.immobilienscout24.de/Suche/de/{location_slug}/{location_slug}/{suffix}"
    if provider.key == "immowelt" and location_slug:
        base_path = "kaufen/wohnung" if listing_mode == "buy" else "mietwohnungen"
        return f"https://www.immowelt.de/suche/{base_path}/{location_slug}"
    if provider.key == "homegate":
        query_items = {}
        if search_terms:
            query_items["loc"] = search_terms
        if max_price_eur:
            query_items["ag"] = str(max_price_eur)
        if min_rooms:
            query_items["ac"] = str(min_rooms)
        return _append_query(base_url, query_items)
    if provider.key == "idealista_es" and location_slug:
        if listing_mode == "buy":
            return f"https://www.idealista.com/en/venta-viviendas/{location_slug}/"
        return f"https://www.idealista.com/en/alquiler-viviendas/{location_slug}/"
    if provider.key == "fotocasa" and location_slug:
        mode_segment = "comprar" if listing_mode == "buy" else "alquiler"
        return f"https://www.fotocasa.es/es/{mode_segment}/viviendas/{location_slug}/l"
    if provider.key == "idealista_it" and location_slug:
        if listing_mode == "buy":
            return f"https://www.idealista.it/vendita-case/{location_slug}/"
        return f"https://www.idealista.it/affitto-case/{location_slug}/"
    if provider.key == "idealista_pt" and location_slug:
        if listing_mode == "buy":
            return f"https://www.idealista.pt/en/comprar-casas/{location_slug}/"
        return f"https://www.idealista.pt/en/arrendar-casas/{location_slug}/"
    if provider.key == "seloger":
        query_items = {"projects": "2" if listing_mode == "buy" else "1", "types": "1"}
        if search_terms:
            query_items["places"] = f"[{{ci:search-{search_terms}}}]"
        if max_price_eur:
            query_items["price"] = f"/{max_price_eur}"
        return _append_query(base_url, query_items)
    if provider.key == "bienici" and location_slug:
        mode_segment = "achat" if listing_mode == "buy" else "location"
        query_items = {}
        if min_rooms:
            query_items["minRooms"] = str(min_rooms)
        if max_price_eur:
            query_items["maxPrice"] = str(max_price_eur)
        return _append_query(f"https://www.bienici.com/recherche/{mode_segment}/{location_slug}", query_items)
    if provider.key == "funda" and location_slug:
        mode_segment = "koop" if listing_mode == "buy" else "huur"
        query_items = {}
        property_segment = _provider_property_type_segment(property_type)
        if property_segment:
            query_items["object_type"] = property_segment
        if min_rooms:
            query_items["min_kamers"] = str(min_rooms)
        return _append_query(f"https://www.funda.nl/zoeken/{mode_segment}/{location_slug}/", query_items)
    if provider.key == "pararius":
        query_items = {}
        if search_terms:
            query_items["q"] = search_terms
        if min_rooms:
            query_items["bedrooms"] = str(min_rooms)
        if max_price_eur:
            query_items["price_to"] = str(max_price_eur)
        return _append_query(base_url, query_items)
    if provider.key == "immoweb":
        query_items = {}
        if search_terms:
            query_items["q"] = search_terms
        if max_price_eur:
            query_items["maxPrice"] = str(max_price_eur)
        if min_rooms:
            query_items["minBedroomCount"] = str(min_rooms)
        return _append_query(base_url, query_items)
    if provider.key == "daft_ie" and location_slug:
        if listing_mode == "buy":
            return f"https://www.daft.ie/property-for-sale/{location_slug}"
        return f"https://www.daft.ie/property-for-rent/{location_slug}"
    if provider.key == "myhome_ie":
        query_items = {}
        if search_terms:
            query_items["query"] = search_terms
        return _append_query(base_url, query_items)
    if provider.key == "realestate_au":
        query_items = {}
        if search_terms:
            query_items["keywords"] = search_terms
        if max_price_eur:
            query_items["maxPrice"] = str(max_price_eur)
        if min_rooms:
            query_items["bedrooms"] = str(min_rooms)
        return _append_query(base_url, query_items)
    if provider.key == "domain_au":
        query_items = {}
        if search_terms:
            query_items["suburb"] = search_terms
        if max_price_eur:
            query_items["price-max"] = str(max_price_eur)
        if min_rooms:
            query_items["bedrooms"] = str(min_rooms)
        return _append_query(base_url, query_items)
    if provider.key == "imovirtual":
        query_items = {}
        if search_terms:
            query_items["q"] = search_terms
        if max_price_eur:
            query_items["priceMax"] = str(max_price_eur)
        return _append_query(base_url, query_items)
    if provider.key == "otodom":
        query_items = {}
        if search_terms:
            query_items["locations"] = search_terms
        if max_price_eur:
            query_items["priceMax"] = str(max_price_eur)
        if min_rooms:
            query_items["roomsNumberMin"] = str(min_rooms)
        return _append_query(base_url, query_items)
    if provider.key == "realtor_ca":
        query_items = {}
        if search_terms:
            query_items["searchtext"] = search_terms
        if max_price_eur:
            query_items["price-max"] = str(max_price_eur)
        return _append_query(base_url, query_items)
    if provider.key == "rew_ca":
        query_items = {}
        if search_terms:
            query_items["query"] = search_terms
        if max_price_eur:
            query_items["price_max"] = str(max_price_eur)
        if min_rooms:
            query_items["bedrooms"] = str(min_rooms)
        return _append_query(base_url, query_items)
    if provider.key == "rightmove":
        query_items = {"searchLocation": location_query or keywords}
        if max_price_eur:
            query_items["maxPrice"] = str(max_price_eur)
        if min_rooms:
            query_items["minBedrooms"] = str(min_rooms)
        return _append_query(base_url, query_items)
    if provider.key == "zoopla":
        query_items = {"q": location_query or keywords}
        if max_price_eur:
            query_items["price_max"] = str(max_price_eur)
        if min_rooms:
            query_items["beds_min"] = str(min_rooms)
        return _append_query(base_url, query_items)
    if provider.key == "realtor":
        query_items = {"view": "list", "query": location_query or keywords}
        if min_rooms:
            query_items["beds-min"] = str(min_rooms)
        if max_price_eur:
            query_items["price-max"] = str(max_price_eur)
        return _append_query(base_url, query_items)
    if provider.key == "zillow":
        query_items = {"query": location_query or keywords}
        if min_rooms:
            query_items["beds"] = str(min_rooms)
        if max_price_eur:
            query_items["price"] = f"-{max_price_eur}"
        return _append_query(base_url, query_items)
    query_items: dict[str, str] = {}
    if search_terms:
        query_items["q"] = search_terms
    if max_price_eur:
        query_items["maxPrice"] = str(max_price_eur)
    if min_rooms:
        query_items["minRooms"] = str(min_rooms)
    if property_type and property_type != "any":
        query_items["propertyType"] = property_type
    return _append_query(base_url, query_items)


def generated_source_specs(
    *,
    preferences: dict[str, object] | None,
    selected_platforms: tuple[str, ...] | list[str] | None,
    principal_id: str = "",
    default_person_id: str = "self",
    notify_telegram: bool = True,
    max_results: int | None = None,
) -> tuple[dict[str, object], ...]:
    normalized_preferences = normalize_property_search_preferences(preferences)
    country_code = str(normalized_preferences.get("country_code") or "AT").strip().upper() or "AT"
    listing_mode = str(normalized_preferences.get("listing_mode") or "rent").strip().lower() or "rent"
    location_query = str(normalized_preferences.get("location_query") or "").strip()
    keywords = str(normalized_preferences.get("keywords") or "").strip()
    property_type = str(normalized_preferences.get("property_type") or "any").strip().lower() or "any"
    max_price_eur = normalized_preferences.get("max_price_eur")
    min_rooms = normalized_preferences.get("min_rooms")
    requested_platforms = [normalize_property_platform(item) for item in (selected_platforms or ())]
    effective_platforms = [item for item in requested_platforms if item and item != "all"]
    if not effective_platforms:
        effective_platforms = list(default_platforms_for_country(country_code))
    location_queries = _location_query_variants(location_query)
    rows: list[dict[str, object]] = []
    for provider_key in effective_platforms:
        provider = _PROVIDER_INDEX.get(provider_key)
        if provider is None or provider.country_code != country_code:
            continue
        provider_mode = listing_mode if listing_mode in provider.supported_listing_modes else provider.supported_listing_modes[0]
        base_url = str(provider.search_urls.get(provider_mode) or next(iter(provider.search_urls.values()), "")).strip()
        if not base_url:
            continue
        for location_variant in location_queries:
            url = _build_provider_search_url(
                provider=provider,
                base_url=base_url,
                listing_mode=provider_mode,
                location_query=location_variant,
                keywords=keywords,
                property_type=property_type,
                max_price_eur=int(max_price_eur) if isinstance(max_price_eur, int) else None,
                min_rooms=int(min_rooms) if isinstance(min_rooms, int) else None,
            )
            detail_parts = [provider.label, country_label(country_code), LISTING_MODE_LABELS.get(provider_mode, provider_mode.capitalize())]
            if location_variant:
                detail_parts.append(location_variant)
            rows.append(
                {
                    "url": url,
                    "label": " | ".join(detail_parts),
                    "principal_id": str(principal_id or "").strip(),
                    "preference_person_id": str(normalized_preferences.get("preference_person_id") or default_person_id or "self").strip() or "self",
                    "account_email": "",
                    "notify_telegram": bool(notify_telegram),
                    "platform": provider.key,
                    "max_results": max(1, min(int(max_results or 5), 10)),
                    "country_code": country_code,
                    "language_code": str(normalized_preferences.get("language_code") or "en"),
                    "listing_mode": provider_mode,
                    "location_query": location_variant,
                    "keywords": keywords,
                }
            )
    return tuple(rows)

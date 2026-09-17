from channel_publishers.providers import DovizComBankRatesProvider
from channel_publishers.renderers import render_bank_comparison, render_kiani_rates


SAMPLE_HTML = """
<table>
  <tr><th>Banka</th><th>Alış</th><th>Satış</th><th>Makas</th></tr>
  <tr><td>Kapalıçarşı</td><td>48,6900</td><td>48,7000</td><td>0,0100</td></tr>
  <tr><td>Garanti BBVA</td><td>47,8320</td><td>49,1820</td><td>1,3500</td></tr>
  <tr><td>İş Bankası</td><td>48,0524</td><td>49,2155</td><td>1,1631</td></tr>
  <tr><td>Kuveyt Türk</td><td>48,2721</td><td>49,2971</td><td>1,0250</td></tr>
  <tr><td>Ziraat Bankası</td><td>48,2651</td><td>49,2415</td><td>0,9764</td></tr>
</table>
"""


def test_doviz_html_parser_extracts_requested_institutions():
    wanted = {
        "Kapalıçarşı",
        "Garanti BBVA",
        "İş Bankası",
        "Kuveyt Türk",
        "Ziraat Bankası",
    }
    rates = DovizComBankRatesProvider.parse_html(SAMPLE_HTML, "USD", wanted)
    by_name = {item.institution: item for item in rates}

    assert set(by_name) == wanted
    assert by_name["Kapalıçarşı"].buy == 48.69
    assert by_name["Kapalıçarşı"].sell == 48.70
    assert by_name["Ziraat Bankası"].sell == 49.2415


def test_bank_comparison_sorts_by_customer_buy_price():
    wanted = {
        "Kapalıçarşı",
        "Garanti BBVA",
        "İş Bankası",
        "Kuveyt Türk",
        "Ziraat Bankası",
    }
    rates = DovizComBankRatesProvider.parse_html(SAMPLE_HTML, "USD", wanted)
    text = render_bank_comparison(rates, "USD")

    assert text.index("Kapalıçarşı") < text.index("Garanti BBVA")
    assert "۱٬۰۰۰" in text
    assert "TL" in text


def test_kiani_renderer_keeps_transaction_brand_separate():
    text = render_kiani_rates(
        {
            "TRY": {"buy": 4600, "sell": 4770},
            "USD": {"buy": 228000, "sell": 229500},
        }
    )
    assert "صرافی کیانی" in text
    assert "خرید از شما" in text
    assert "فروش به شما" in text
    assert "@alanchande_com" in text

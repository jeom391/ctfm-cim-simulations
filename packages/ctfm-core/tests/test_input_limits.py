import io
import pytest
from openpyxl import Workbook
import ctfm.measurement as measurement

def test_parser_row_limits_apply_to_csv_and_xlsx(monkeypatch):
    monkeypatch.setattr(measurement,"MAX_ROWS",3)
    with pytest.raises(ValueError,match="limit"):
        measurement.parse_table(b"a,b\n1,2\n3,4\n5,6\n","test.csv")
    workbook=Workbook();sheet=workbook.active
    for row in [["a","b"],[1,2],[3,4],[5,6]]:sheet.append(row)
    buffer=io.BytesIO();workbook.save(buffer)
    with pytest.raises(ValueError,match="limit"):
        measurement.parse_table(buffer.getvalue(),"test.xlsx")

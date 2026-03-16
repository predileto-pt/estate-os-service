from mangum import Mangum

from shared.main import create_app

app = create_app()
handler = Mangum(app, lifespan="off")

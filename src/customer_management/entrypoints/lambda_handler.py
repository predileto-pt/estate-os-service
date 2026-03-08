from mangum import Mangum

from customer_management.main import create_app

app = create_app()
handler = Mangum(app, lifespan="off")

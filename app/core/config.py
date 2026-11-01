from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMARTFARM_", extra="ignore")

    app_name: str = "Smart Farm System API"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    archive_path: str = "/mnt/smartfarm-data/archive"
    openweather_api_key: str | None = None

    # Optional Zigbee MQTT worker configuration.
    zigbee_mqtt_host: str | None = None
    zigbee_mqtt_port: int = 1883
    zigbee_mqtt_keepalive: int = 60
    zigbee_mqtt_client_id: str = "smartfarm-zigbee"
    zigbee_mqtt_username: str | None = None
    zigbee_mqtt_password: str | None = None
    zigbee_mqtt_qos: int = 1
    zigbee_mqtt_connect_timeout: float = 15.0
    zigbee_mqtt_subscribe_timeout: float = 10.0
    zigbee_base_topic: str = "zigbee2mqtt"


settings = Settings()

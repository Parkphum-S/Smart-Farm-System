from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict()

    email: str = Field(min_length=4, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if (
            value.count("@") != 1
            or value.startswith("@")
            or value.endswith("@")
            or "." not in value.rsplit("@", 1)[1]
            or any(char.isspace() for char in value)
        ):
            raise ValueError("Invalid email address")
        return value


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

import os
from typing import List

class EnvironmentValidator:
    """Utility class for validating environment variables"""
    
    @staticmethod
    def validate_required_vars(required_vars: List[str]) -> None:
        """Validate that all required environment variables are present"""
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        
        if missing_vars:
            raise EnvironmentError(
                f"Missing environment variable(s): {', '.join(missing_vars)}"
            )
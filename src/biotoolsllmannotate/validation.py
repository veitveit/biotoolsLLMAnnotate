"""Configuration validation utilities."""

from typing import Any, Dict, List
from urllib.parse import urlparse


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


def validate_config(config: Dict[str, Any]) -> List[str]:
    """
    Validate configuration and return list of errors.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    # Validate Ollama configuration
    ollama_config = config.get("ollama", {})
    host = ollama_config.get("host", "")
    if host:
        parsed = urlparse(host)
        if not parsed.scheme or not parsed.netloc:
            errors.append(f"Invalid Ollama host URL: {host}")
    
    # Validate pipeline configuration
    pipeline_config = config.get("pipeline", {})
    
    # Validate concurrency
    concurrency = pipeline_config.get("concurrency", 8)
    if not isinstance(concurrency, int) or concurrency < 1:
        errors.append(f"Invalid concurrency value: {concurrency} (must be positive integer)")
    if concurrency > 32:
        errors.append(f"Concurrency value {concurrency} may be too high (recommended: ≤32)")
    
    # Validate model name
    model = pipeline_config.get("model", "")
    if model and not isinstance(model, str):
        errors.append(f"Model name must be a string, got {type(model)}")
    
    # Validate timeout values
    enrichment_config = config.get("enrichment", {})
    for service, service_config in enrichment_config.items():
        if isinstance(service_config, dict) and "timeout" in service_config:
            timeout = service_config["timeout"]
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                errors.append(f"Invalid timeout for {service}: {timeout} (must be positive number)")
    
    # Validate file paths
    logging_config = config.get("logging", {})
    log_file = logging_config.get("file")
    if log_file and not isinstance(log_file, str):
        errors.append(f"Log file path must be a string, got {type(log_file)}")
    
    return errors


def validate_and_raise(config: Dict[str, Any]) -> None:
    """
    Validate configuration and raise exception if invalid.
    
    Args:
        config: Configuration dictionary
        
    Raises:
        ConfigValidationError: If validation fails
    """
    errors = validate_config(config)
    if errors:
        raise ConfigValidationError("Configuration validation failed:\n" + "\n".join(f"  - {error}" for error in errors))
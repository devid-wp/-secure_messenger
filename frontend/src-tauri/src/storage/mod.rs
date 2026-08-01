use std::fmt;
use std::io;

#[derive(Debug)]
pub enum StorageError {
    Io(io::Error),
    Platform(String),
    InvalidData(&'static str),
    Locked,
}

impl fmt::Display for StorageError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "native storage I/O failed: {error}"),
            Self::Platform(message) => write!(formatter, "platform protection failed: {message}"),
            Self::InvalidData(message) => {
                write!(formatter, "native storage data is invalid: {message}")
            }
            Self::Locked => formatter.write_str("native storage is locked"),
        }
    }
}

impl std::error::Error for StorageError {}

impl From<io::Error> for StorageError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn errors_do_not_include_secret_values() {
        assert_eq!(StorageError::Locked.to_string(), "native storage is locked");
        assert!(StorageError::InvalidData("bad envelope")
            .to_string()
            .contains("bad envelope"));
    }
}

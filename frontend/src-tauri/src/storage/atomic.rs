use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use super::StorageError;

#[derive(Clone, Copy)]
pub enum WriteMode {
    Replace,
    CreateNew,
}

struct TemporaryFile(PathBuf);

impl Drop for TemporaryFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

pub fn write(path: &Path, data: &[u8], mode: WriteMode) -> Result<(), StorageError> {
    let parent = path
        .parent()
        .ok_or(StorageError::InvalidData("storage path has no parent"))?;
    fs::create_dir_all(parent)?;

    let (temporary, mut file) = create_temporary(path)?;
    file.write_all(data)?;
    file.sync_all()?;
    drop(file);

    publish(&temporary.0, path, mode)?;
    sync_directory(parent)?;
    Ok(())
}

fn create_temporary(path: &Path) -> Result<(TemporaryFile, File), StorageError> {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(StorageError::InvalidData("storage file name is invalid"))?;
    for _ in 0..16 {
        let mut random = [0_u8; 8];
        getrandom::fill(&mut random)
            .map_err(|error| StorageError::Platform(format!("random generation failed: {error}")))?;
        let temporary_path = path.with_file_name(format!(
            ".{file_name}.{}.tmp",
            u64::from_le_bytes(random)
        ));
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary_path)
        {
            Ok(file) => return Ok((TemporaryFile(temporary_path), file)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    }
    Err(StorageError::Io(io::Error::new(
        io::ErrorKind::AlreadyExists,
        "could not allocate a temporary storage file",
    )))
}

#[cfg(windows)]
fn publish(source: &Path, destination: &Path, mode: WriteMode) -> Result<(), StorageError> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination: Vec<u16> = destination.as_os_str().encode_wide().chain(Some(0)).collect();
    let flags = MOVEFILE_WRITE_THROUGH
        | match mode {
            WriteMode::Replace => MOVEFILE_REPLACE_EXISTING,
            WriteMode::CreateNew => 0,
        };
    if unsafe { MoveFileExW(source.as_ptr(), destination.as_ptr(), flags) } == 0 {
        return Err(io::Error::last_os_error().into());
    }
    Ok(())
}

#[cfg(not(windows))]
fn publish(source: &Path, destination: &Path, mode: WriteMode) -> Result<(), StorageError> {
    match mode {
        WriteMode::Replace => fs::rename(source, destination)?,
        WriteMode::CreateNew => {
            fs::hard_link(source, destination)?;
            fs::remove_file(source)?;
        }
    }
    Ok(())
}

fn sync_directory(path: &Path) -> Result<(), StorageError> {
    #[cfg(not(windows))]
    File::open(path)?.sync_all()?;
    #[cfg(windows)]
    let _ = path;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temporary_path(name: &str) -> PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("secure-messenger-atomic-{name}-{suffix}"))
    }

    #[test]
    fn replace_publishes_complete_new_contents() {
        let path = temporary_path("replace");
        fs::write(&path, b"old").unwrap();
        write(&path, b"complete new contents", WriteMode::Replace).unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"complete new contents");
        fs::remove_file(path).unwrap();
    }

    #[test]
    fn create_new_preserves_existing_contents() {
        let path = temporary_path("create-new");
        fs::write(&path, b"existing").unwrap();
        assert!(write(&path, b"replacement", WriteMode::CreateNew).is_err());
        assert_eq!(fs::read(&path).unwrap(), b"existing");
        fs::remove_file(path).unwrap();
    }
}

from setuptools import setup, find_packages


setup(
    name="stytra",
    version="0.8.34",
    author="Vilim Stih, Luigi Petrucco @portugueslab",
    author_email="vilim@neuro.mpg.de",
    license="GPLv3+",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "pyqtgraph>=0.10.0",
        "numpy",
        "numba",
        "pandas",
        "scipy",
        "qdarkstyle",
        "qimage2ndarray",
        "tables",
        "anytree",
        "pims",
        "GitPython",
        "colorspacious",
        "pillow",
        "scikit-image",
        "opencv-python",
        "imageio",
        "imageio-ffmpeg",
        "pyfirmata2",
        "zarr>=3.0",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        # Pick your license as you wish (should match "license" above)
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="tracking behavior experiments",
    description="A modular package to control stimulation and track behavior experiments.",
    project_urls={
        "Source": "https://github.com/portugueslab/stytra",
        "Tracker": "https://github.com/portugueslab/stytra/issues",
    },
    include_package_data=True,
)

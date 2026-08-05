class UserCreateRequest {
  UserCreateRequest({
    required this.name,
    this.phoneNumber,
    this.ageGroup,
    this.gender,
  });

  final String name;
  final String? phoneNumber;
  final String? ageGroup;
  final String? gender;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'name': name,
    if (phoneNumber != null) 'phoneNumber': phoneNumber,
    if (ageGroup != null) 'ageGroup': ageGroup,
    if (gender != null) 'gender': gender,
  };
}

class UserResponse {
  UserResponse({
    required this.userId,
    required this.name,
    required this.phoneNumber,
    this.ageGroup,
    this.gender,
    this.createdAt,
    this.updatedAt,
  });

  final int userId;
  final String name;
  final String phoneNumber;
  final String? ageGroup;
  final String? gender;
  final String? createdAt;
  final String? updatedAt;

  factory UserResponse.fromJson(Map<String, dynamic> json) {
    return UserResponse(
      userId: json['userId'] as int,
      name: json['name'] as String,
      phoneNumber: json['phoneNumber'] as String,
      ageGroup: json['ageGroup'] as String?,
      gender: json['gender'] as String?,
      createdAt: json['createdAt'] as String?,
      updatedAt: json['updatedAt'] as String?,
    );
  }
}
